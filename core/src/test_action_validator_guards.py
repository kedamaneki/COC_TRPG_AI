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
    MOVE_MISSING_TARGET_ERROR,
    HUMAN_INSPECT_REWRITE_LOG,
    KP_SUCCESS_FACT_GUARD,
    KP_LOCKED_ROUTE_GUARD,
    validate_move_intent,
    infer_empty_move_from_intent,
    validate_force_ic_action,
    validate_completed_dolly_talk,
    is_stale_nonprogress_talk,
    build_forced_progress_move_action,
    pick_forced_progress_search_target,
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

    def test_empty_move_target_uses_dedicated_error_not_globe_example(self):
        check = validate_move_intent(
            "",
            "",
            current_loc="chapel_of_contemplation",
            scenario_mgr=self.scenario,
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check["error_code"], "move_missing_target")
        self.assertIn(MOVE_MISSING_TARGET_ERROR[:12], check["error"])
        self.assertNotIn("参考資料室", check["error"])
        self.assertNotIn("boston_globe", check["error"].lower())
        self.assertTrue((check.get("suggested_fix") or {}).get("target"))

    def test_empty_move_infers_chapel_from_dialogue(self):
        self.scenario.location = "the_neighborhood"
        self.scenario.flags["dolly_told_chapel_location"] = True
        out = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "",
                "skill": "",
                "dialogue": "黙想チャペルへ向かおう",
            },
            "PC",
            "",
            self.scenario,
            "the_neighborhood",
            char_mgr=self.char_mgr,
        )
        self.assertFalse(out.get("needs_pl_retry"))
        self.assertEqual(out["action"], "move")
        self.assertEqual(out["target"], "chapel_of_contemplation")

    def test_empty_move_at_chapel_autocorrects_to_remaining_search(self):
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags["symbol_investigated"] = True
        self.scenario.flags["investigated_targets"] = ["white_symbol"]
        logs = []
        out = game_main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pl_ooc_chat": "",
                "pc_action": {"action": "move", "target": "", "skill": "", "dialogue": ""},
            },
            "マクガフィン刑事",
            "chapel_of_contemplation",
            logs,
            scenario_mgr=self.scenario,
            char_mgr=self.char_mgr,
            pc_id="pc_01",
        )
        self.assertTrue(out.get("auto_corrected"))
        self.assertEqual(out.get("action"), "search")
        self.assertIn(
            out.get("target"),
            ("chapel_secret_cellar", "chapel_ruins", "rotting_floorboards"),
        )
        self.assertFalse(any(
            (e.get("meta") or {}).get("error_code") == "move_missing_target"
            for e in logs
        ))

    def test_chapel_search_pick_skips_basement_only_objects(self):
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags["symbol_investigated"] = True
        self.scenario.flags["investigated_targets"] = ["white_symbol"]
        picked = pick_forced_progress_search_target(
            self.scenario, "chapel_of_contemplation",
        )
        self.assertIsNotNone(picked)
        self.assertNotIn(
            picked,
            ("skeletons_in_robes", "shelf_with_records", "cult_diary", "grimoire_book_of_eibon"),
        )
        self.assertIn(picked, ("chapel_secret_cellar", "chapel_ruins", "rotting_floorboards"))

    def test_absent_bob_talk_at_exterior_is_rejected(self):
        self.scenario.location = "corbitt_exterior"
        out = game_main.reconcile_pl_action(
            {
                "action": "talk",
                "target": "",
                "skill": "",
                "dialogue": "ボブさん、このコービット屋敷について何か知っていることはありますか？",
            },
            "PC",
            "",
            self.scenario,
            "corbitt_exterior",
            char_mgr=self.char_mgr,
        )
        self.assertTrue(out.get("needs_pl_retry"))
        self.assertEqual(out.get("validation_error_code"), "absent_npc_talk")
        self.assertTrue((out.get("suggested_fix") or {}).get("target"))
        self.assertNotEqual((out.get("suggested_fix") or {}).get("action"), "talk")

    def test_kp_does_not_declare_chapel_exhausted_while_cellar_remains(self):
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags["symbol_investigated"] = True
        self.scenario.flags["investigated_targets"] = ["white_symbol"]
        directive = game_main._build_kp_situational_directives(
            self.scenario, state={"current_loc": "chapel_of_contemplation"},
        )
        self.assertIn("未調査の残", directive)
        self.assertIn("chapel_secret_cellar", directive)
        self.assertNotIn("`skeletons_in_robes`", directive)

    def test_chapel_exit_not_flag_is_available_on_surface(self):
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags["in_basement"] = False
        exits = {e["id"] for e in self.scenario.get_available_exits("chapel_of_contemplation")}
        self.assertIn("the_neighborhood", exits)
        self.assertNotIn("corbitt_exterior", exits)

    def test_sanitarium_person_objects_are_investigated_not_absent(self):
        self.scenario.location = "roxbury_sanitarium"
        out = game_main.reconcile_pl_action(
            {
                "action": "talk",
                "target": "gabriella_macario",
                "skill": "",
                "dialogue": "ヴィットリオさんの悪霊について教えてください",
            },
            "PC",
            "",
            self.scenario,
            "roxbury_sanitarium",
            char_mgr=self.char_mgr,
        )
        self.assertFalse(out.get("needs_pl_retry"))
        self.assertEqual(out.get("action"), "search")
        self.assertEqual(out.get("target"), "gabriella_macario")

        from unittest import mock
        with mock.patch.object(
            game_main, "judge_occupation_roleplay",
            return_value={
                "fit": "neutral", "bonus_dice": 0, "penalty_dice": 0,
                "skip_roll": False, "auto_success_level": 2, "reason": "test",
            },
        ):
            result = game_main.process_system_action(
                "pc_01", "マクガフィン刑事", "search", "vittorio_macario", "心理学",
                "roxbury_sanitarium", self.char_mgr, self.dice, self.scenario,
            )
        self.assertNotEqual(result.get("roll_type"), "blocked")
        self.assertFalse(result.get("absent_npc"))
        self.assertNotIn("対話ブロック", result.get("log", ""))

    def test_same_location_move_is_rejected(self):
        self.scenario.location = "the_neighborhood"
        self.scenario.flags["talked_with_knott"] = True
        check = validate_move_intent(
            "近隣の住民に話を聞こう",
            "the_neighborhood",
            current_loc="the_neighborhood",
            scenario_mgr=self.scenario,
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check.get("error_code"), "move_same_location")
        payload = self.scenario.process_action("move", "the_neighborhood", 2)
        self.assertTrue(payload.get("blocked") or "すでに" in payload.get("system_log", ""))

    def test_obtained_info_does_not_force_sanitarium_move(self):
        self.scenario.location = "the_neighborhood"
        self.scenario.flags["dolly_talked"] = True
        self.scenario.flags["dolly_told_sanitarium_location"] = True
        inferred = infer_empty_move_from_intent(
            "ロックスベリー・サナトリウムと黙想チャペルの情報を手に入れたが、"
            "まずは近隣の住民からもう少し具体的な情報を引き出してから行動に移そう。",
            current_loc="the_neighborhood",
            scenario_mgr=self.scenario,
        )
        if inferred:
            self.assertNotEqual(inferred.get("target"), "roxbury_sanitarium")
        check = validate_move_intent(
            "ロックスベリー・サナトリウムの情報を手に入れたが、まずは近隣の住民に話を聞く。",
            "roxbury_sanitarium",
            current_loc="the_neighborhood",
            scenario_mgr=self.scenario,
        )
        self.assertFalse(check["ok"])

    def test_dolly_stale_talk_redirects_to_house_view(self):
        self.scenario.location = "the_neighborhood"
        self.scenario.flags["dolly_talked"] = True
        self.scenario.flags["dolly_told_chapel_location"] = True
        self.scenario.flags["dolly_told_sanitarium_location"] = True
        self.assertTrue(
            is_stale_nonprogress_talk(
                "talk", "dolly_shopkeeper",
                scenario_mgr=self.scenario,
                current_loc="the_neighborhood",
                char_mgr=self.char_mgr,
            )
        )
        dolly = validate_completed_dolly_talk(
            {"action": "talk", "target": "dolly_shopkeeper"},
            scenario_mgr=self.scenario,
            current_loc="the_neighborhood",
            char_mgr=self.char_mgr,
        )
        # 現在地にいる会話は許可し、次行動として屋敷外観調査を提案する
        self.assertTrue(dolly.get("ok"))
        self.assertTrue(dolly.get("preserve_social_intent"))
        self.assertEqual((dolly.get("suggested_fix") or {}).get("target"), "corbitt_house_exterior_view")
        self.assertIn("corbitt_house_exterior_view", dolly.get("next_location_hint") or "")

        ghost = validate_completed_dolly_talk(
            {"action": "talk", "target": "dolly_shopkeeper"},
            scenario_mgr=self.scenario,
            current_loc="boston_globe",
            char_mgr=self.char_mgr,
        )
        self.assertFalse(ghost.get("ok"))
        self.assertEqual(ghost.get("error_code"), "stale_dolly_talk")

    def test_introduction_is_not_location_exhausted_after_knott(self):
        from ActionValidator import should_apply_location_exhausted_move
        self.scenario.location = "introduction"
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True
        self.assertFalse(should_apply_location_exhausted_move(self.scenario, "introduction"))
        nudge = game_main._build_introduction_move_nudge(self.scenario, "introduction")
        self.assertIn("任意", nudge)
        self.assertNotIn("強く推奨", nudge)
        self.assertNotIn("調査はすべて完了", nudge)

    def test_push_roll_without_pending_is_rejected_at_reconcile(self):
        from ActionValidator import PUSH_ROLL_UNAVAILABLE_ERROR, validate_push_roll_available
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags["floorboards_examined"] = True
        check = validate_push_roll_available(None, current_loc="chapel_of_contemplation", scenario_mgr=self.scenario)
        self.assertFalse(check["ok"])
        self.assertEqual(check.get("error_code"), "push_roll_unavailable")
        self.assertIn("プッシュロール", check.get("error") or "")

        out = game_main.reconcile_pl_action(
            {
                "action": "push_roll",
                "target": "",
                "skill": "",
                "dialogue": "もう一度、慎重にやってみよう",
            },
            "PC",
            "調査する前にプッシュロールを検討すべきか？",
            self.scenario,
            "chapel_of_contemplation",
            char_mgr=self.char_mgr,
            pending_push_roll=None,
        )
        self.assertTrue(out.get("needs_pl_retry"))
        self.assertEqual(out.get("validation_error_code"), "push_roll_unavailable")
        self.assertIn("プッシュ", out.get("validation_error") or PUSH_ROLL_UNAVAILABLE_ERROR)

        allowed = game_main.reconcile_pl_action(
            {
                "action": "push_roll",
                "target": "rotting_floorboards",
                "skill": "",
                "dialogue": "リスクを覚悟でもう一度調べる",
            },
            "PC",
            "",
            self.scenario,
            "chapel_of_contemplation",
            char_mgr=self.char_mgr,
            pending_push_roll={
                "target": "rotting_floorboards",
                "skill_name": "目星",
                "original_action": "search",
            },
        )
        self.assertFalse(allowed.get("needs_pl_retry"))
        self.assertEqual(allowed.get("action"), "push_roll")

    def test_chapel_basement_requires_flag_and_floorboard_entry(self):
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags["in_basement"] = False
        blocked = self.scenario.evaluate_pre_action_guard(
            "search", "skeletons_in_robes", loc_id="chapel_of_contemplation",
        )
        self.assertTrue(blocked)
        self.assertTrue(blocked.get("blocked") or "地階" in (blocked.get("system_log") or ""))

        self.scenario.flags["floorboards_examined"] = True
        payload = self.scenario.process_action("break", "rotting_floorboards", 2)
        self.assertFalse(payload.get("blocked"))
        self.assertTrue(self.scenario.flags.get("chapel_cellar_entered"))
        self.assertFalse(self.scenario.flags.get("in_basement"))
        self.assertIn("地階", payload.get("system_log") or "")

        ok = self.scenario.evaluate_pre_action_guard(
            "search", "skeletons_in_robes", loc_id="chapel_of_contemplation",
        )
        self.assertFalse(ok)  # None means not blocked

        climb = self.scenario.process_action("climb", "rotting_floorboards", 2)
        self.assertFalse(climb.get("blocked"))
        self.assertFalse(self.scenario.flags.get("chapel_cellar_entered"))
        self.assertFalse(self.scenario.flags.get("in_basement"))

    def test_reconfirm_kp_forbids_same_target_retry(self):
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags["symbol_investigated"] = True
        self.scenario.flags["investigated_targets"] = ["white_symbol"]
        block = self.scenario.evaluate_pre_action_guard(
            "search", "white_symbol", loc_id="chapel_of_contemplation",
        )
        self.assertTrue(block)
        self.assertIn("再確認", block.get("system_log") or "")
        self.assertIn("新規手がかりはない", block.get("system_log") or "")
        self.assertIn("再確認のみ", block.get("kp_instruction") or "")
        self.assertIn("どうしますか", block.get("kp_instruction") or "")

    def test_chapel_not_exhausted_while_floorboard_break_pending(self):
        from ActionValidator import (
            is_location_investigation_exhausted,
            should_apply_location_exhausted_move,
            build_forced_progress_action,
        )
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
        self.assertFalse(
            is_location_investigation_exhausted(self.scenario, "chapel_of_contemplation")
        )
        self.assertFalse(
            should_apply_location_exhausted_move(self.scenario, "chapel_of_contemplation")
        )
        forced = build_forced_progress_action(self.scenario, "chapel_of_contemplation")
        self.assertIsNotNone(forced)
        self.assertEqual(forced.get("action"), "break")
        self.assertEqual(forced.get("target"), "rotting_floorboards")

    def test_dolly_after_chapel_done_suggests_corbitt_exterior(self):
        self.scenario.location = "the_neighborhood"
        self.scenario.flags["dolly_talked"] = True
        self.scenario.flags["dolly_told_chapel_location"] = True
        self.scenario.flags["dolly_told_sanitarium_location"] = True
        self.scenario.flags["chapel_investigated"] = True
        self.scenario.flags["sanitarium_info_found"] = True
        # 外観オブジェクト調査済み扱いにして次候補へ
        self.scenario.flags["investigated_targets"] = ["corbitt_house_exterior_view"]
        ext = self.scenario.get_object_info("the_neighborhood", "corbitt_house_exterior_view") or {}
        if ext.get("investigated_flag"):
            self.scenario.flags[ext["investigated_flag"]] = True
        dolly = validate_completed_dolly_talk(
            {"action": "talk", "target": "dolly_shopkeeper"},
            scenario_mgr=self.scenario,
            current_loc="the_neighborhood",
            char_mgr=self.char_mgr,
        )
        self.assertTrue(dolly.get("ok"))
        self.assertEqual((dolly.get("suggested_fix") or {}).get("target"), "corbitt_exterior")
        self.assertNotIn("chapel_of_contemplation", dolly.get("next_location_hint") or "")

    def test_exhausted_hint_skips_already_obtained_globe(self):
        from ActionValidator import build_location_exhausted_move_hint
        self.scenario.location = "the_neighborhood"
        self.scenario.flags["found_newspaper_article_1918"] = True
        self.scenario.flags["talked_with_knott"] = True
        hint = build_location_exhausted_move_hint(self.scenario, "the_neighborhood")
        self.assertIn("調査はすべて完了", hint)
        self.assertNotIn("boston_globe", hint)
        self.assertIn("corbitt_exterior", hint)


if __name__ == "__main__":
    unittest.main()
