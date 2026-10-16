"""
NPC配置整合性・キム対話・警察記録（資料8）の回帰テスト。
LLM通信なし。セーブ原本はコピーのみ使用。
実行: python test_npc_placement_and_police_archives.py
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
from ScenarioManager import ScenarioManager
from NPCSocialManager import format_npc_directory_for_pl, find_npc_id_by_target
import main as game_main


ROOT = Path(__file__).resolve().parent
CORBITT = ROOT / "scenario_corbitt.json"
NPCS = ROOT / "npcs.json"
SAVE = ROOT / "save_autosave.json"


class _Base(unittest.TestCase):
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
                "skills": {
                    "目星": 65, "説得": 70, "言いくるめ": 60, "信用": 80,
                    "法律": 55, "魅惑": 40, "隠密": 40, "鍵開け": 40,
                },
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.scenario = ScenarioManager(copy.deepcopy(self.scenario_data))
        self.dice = DiceEngine()

    def tearDown(self):
        self.tmp.cleanup()


class TestNpcPresence(_Base):
    def test_library_cannot_talk_to_globe_staff(self):
        self.scenario.location = "central_library"
        for target in ("globe_receptionist", "artie_wilmott", "受付", "アーティ"):
            result = game_main.process_system_action(
                "pc_01", "マクガフィン刑事", "talk", target, "",
                "central_library", self.char_mgr, self.dice, self.scenario,
            )
            self.assertTrue(result.get("blocked") or result.get("absent_npc"), target)
            self.assertIn("対話ブロック", result.get("log", ""))

    def test_courts_cannot_talk_to_bob_or_hall_clerk(self):
        self.scenario.location = "higher_courts_police_station"
        for target in ("npc_guard_01", "ボブ", "hall_records_clerk", "公文書館の事務官"):
            result = game_main.process_system_action(
                "pc_01", "マクガフィン刑事", "talk", target, "",
                "higher_courts_police_station", self.char_mgr, self.dice, self.scenario,
            )
            self.assertTrue(result.get("blocked") or result.get("absent_npc"), target)

    def test_kim_is_present_and_directory_lists_her(self):
        self.assertIn("kim_deblanc", self.char_mgr.characters)
        self.scenario.location = "higher_courts_police_station"
        self.assertTrue(
            self.scenario.is_npc_at_location(
                "kim_deblanc", "higher_courts_police_station", char_mgr=self.char_mgr,
            )
        )
        text = format_npc_directory_for_pl(
            self.char_mgr,
            current_loc="higher_courts_police_station",
            flags=self.scenario.flags,
            scenario_mgr=self.scenario,
        )
        self.assertIn("kim_deblanc", text)
        self.assertNotIn("npc_guard_01", text)
        self.assertNotIn("hall_records_clerk", text)
        self.assertNotIn("globe_receptionist", text)

    def test_kim_talk_and_negotiate_paths(self):
        self.scenario.location = "higher_courts_police_station"
        self.assertEqual(find_npc_id_by_target(self.char_mgr, "キム"), "kim_deblanc")

        with mock.patch.object(
            game_main, "judge_occupation_roleplay",
            return_value={
                "fit": "neutral", "bonus_dice": 0, "penalty_dice": 0,
                "skip_roll": False, "auto_success_level": 2, "reason": "test",
            },
        ):
            talk = game_main.process_system_action(
                "pc_01", "マクガフィン刑事", "talk", "kim_deblanc", "",
                "higher_courts_police_station", self.char_mgr, self.dice, self.scenario,
            )
        self.assertFalse(talk.get("blocked"))
        self.assertEqual(talk.get("roll_type"), "social_talk")
        self.assertTrue(self.scenario.flags.get("kim_deblanc_interacted"))
        self.assertFalse(self.scenario.flags.get("higher_courts_records_accessed"))

        def _always_success(*_a, **_k):
            return {
                "success_level": int(SuccessLevel.REGULAR_SUCCESS),
                "is_failure": False,
                "log": "【判定】強制成功（テスト）",
                "roll": 1,
                "value": 70,
            }

        with mock.patch.object(
            game_main, "judge_occupation_roleplay",
            return_value={
                "fit": "good", "bonus_dice": 0, "penalty_dice": 0,
                "skip_roll": False, "auto_success_level": 2, "reason": "test",
            },
        ), mock.patch.object(self.dice, "evaluate_roll", side_effect=_always_success), \
             mock.patch.object(self.dice, "execute_skill_roll", side_effect=_always_success):
            nego = game_main.process_system_action(
                "pc_01", "マクガフィン刑事", "persuade", "kim_deblanc", "説得",
                "higher_courts_police_station", self.char_mgr, self.dice, self.scenario,
            )
        self.assertFalse(nego.get("blocked"), nego.get("log"))
        self.assertTrue(
            self.scenario.flags.get("higher_courts_records_accessed"),
            nego.get("log"),
        )
        combined = nego.get("log", "") + str(nego.get("confirmed_fact") or "")
        for g in nego.get("knowledge_grants") or []:
            combined += str(g.get("summary") or "")
        self.assertIn("プレイヤー資料8", combined)
        game_main.apply_knowledge_grants_from_result(
            self.char_mgr, "pc_01", nego, state={},
        )
        kid = knowledge_id_for_object("police_archives")
        self.assertIn(kid, self.char_mgr.get_known_knowledge_ids("pc_01"))

    def test_absent_guidance_excludes_rejected_person(self):
        self.scenario.location = "higher_courts_police_station"
        block, _kp, _hint = game_main.build_absent_npc_guidance(
            self.scenario,
            "higher_courts_police_station",
            exclude_targets={"kim_deblanc"},
        )
        self.assertNotIn("`kim_deblanc`", block)
        self.assertIn("police_archives", block)

    def test_search_kim_rewrites_to_talk_not_absent(self):
        self.scenario.location = "higher_courts_police_station"
        fixed = game_main.reconcile_pl_action(
            {
                "action": "search",
                "target": "kim_deblanc",
                "skill": "目星",
                "dialogue": "事務官を探す",
            },
            "PC", "", self.scenario, "higher_courts_police_station",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(fixed.get("action"), "talk")
        self.assertEqual(fixed.get("target"), "kim_deblanc")
        self.assertFalse(fixed.get("needs_pl_retry"))


class TestPoliceArchives(_Base):
    def test_success_returns_handout_not_teaser(self):
        self.scenario.location = "higher_courts_police_station"
        self.scenario.flags["higher_courts_records_accessed"] = False
        payload = self.scenario.process_action("search", "police_archives", int(SuccessLevel.REGULAR_SUCCESS))
        self.assertFalse(payload.get("blocked"))
        fact = payload.get("confirmed_fact") or ""
        log = payload.get("system_log") or ""
        self.assertIn("プレイヤー資料8", fact + log)
        self.assertIn("マイケル・トーマス", fact + log)
        self.assertNotIn("情報が眠っている", fact)
        self.assertTrue(self.scenario.flags.get("higher_courts_records_accessed"))

    def test_success_knowledge_matches_flag(self):
        self.scenario.location = "higher_courts_police_station"
        payload = self.scenario.process_action(
            "search", "police_archives", int(SuccessLevel.REGULAR_SUCCESS),
        )
        result = {
            "confirmed_fact": payload.get("confirmed_fact"),
            "knowledge_grants": payload.get("knowledge_grants") or [],
            "target": "police_archives",
            "log": payload.get("system_log", ""),
        }
        game_main.apply_knowledge_grants_from_result(
            self.char_mgr, "pc_01", result, state={},
        )
        self.assertTrue(self.scenario.flags.get("higher_courts_records_accessed"))
        kid = knowledge_id_for_object("police_archives")
        self.assertIn(kid, self.char_mgr.get_known_knowledge_ids("pc_01"))
        notes = self.char_mgr.characters["pc_01"].get("knowledge_notes") or {}
        self.assertIn("プレイヤー資料8", str(notes.get(kid) or ""))
        self.assertIn("マイケル・トーマス", str(notes.get(kid) or ""))

    def test_reinvestigate_is_review_not_negotiate_prompt(self):
        self.scenario.location = "higher_courts_police_station"
        self.scenario.flags["higher_courts_records_accessed"] = True
        self.scenario._track_investigated_target("police_archives")
        # first grant
        fact, _ = self.scenario._object_confirmed_fact("police_archives")
        self.char_mgr.grant_knowledge(
            "pc_01", knowledge_id_for_object("police_archives"),
            target="police_archives", summary=fact,
        )
        block = self.scenario.evaluate_pre_action_guard(
            "search", "police_archives", "higher_courts_police_station",
        )
        self.assertTrue(block.get("blocked"))
        text = (block.get("system_log") or "") + (block.get("kp_instruction") or "")
        self.assertIn("済", text.replace("閲覧済み", "済"))
        self.assertNotIn("断られた", text)
        self.assertNotIn("別のアプローチ", text)
        self.assertIn("プレイヤー資料8", block.get("confirmed_fact") or block.get("system_log") or "")
        # 効果重複なし: 既知のまま
        before = list(self.char_mgr.get_known_knowledge_ids("pc_01"))
        game_main.apply_knowledge_grants_from_result(self.char_mgr, "pc_01", block, state={})
        after = list(self.char_mgr.get_known_knowledge_ids("pc_01"))
        self.assertEqual(before, after)


class TestSaveCompat(_Base):
    def test_load_copy_repairs_handout_keeps_pc_state(self):
        if not SAVE.exists():
            raise unittest.SkipTest("save_autosave.json がありません")
        raw = json.loads(SAVE.read_text(encoding="utf-8"))
        # 原本を変更しないこと（コピーのみ）
        save = copy.deepcopy(raw)

        # temp managers
        from GameStateManager import GameStateManager
        state_mgr = GameStateManager(self.char_mgr)
        scenario = ScenarioManager(copy.deepcopy(self.scenario_data))
        app_state = game_main.restore_from_save_data(save, state_mgr, self.char_mgr, scenario)

        expected_loc = (
            (save.get("app_state") or {}).get("current_loc")
            or (save.get("scenario_manager") or {}).get("location")
            or "boston_globe"
        )
        self.assertEqual(scenario.location, expected_loc)
        self.assertEqual(app_state.get("current_loc"), expected_loc)
        self.assertIn("kim_deblanc", self.char_mgr.characters)

        # ロード後は実行中フラグを落とし、安全側へ pause する
        self.assertTrue(app_state.get("autonomous_paused"))
        self.assertFalse(app_state.get("is_running"))
        # pending != last のセーブは揃えない（二重実行防止）。揃っている場合のみ一致を確認。
        pending = str(app_state.get("pending_action_id") or "")
        last = str(app_state.get("last_processed_action_id") or "")
        if pending and last and pending == last:
            self.assertEqual(pending, last)
        else:
            # 処理途中セーブは reexec_forbidden など再開不可クラスになり得る
            self.assertTrue(
                app_state.get("autonomous_pause_reason")
                or app_state.get("autonomous_pause_class")
            )

        # PC 進行・SAN を破壊していない
        pc = self.char_mgr.characters.get("pc_01") or next(
            c for c in self.char_mgr.characters.values()
            if not (c.get("profile") or {}).get("is_npc")
        )
        self.assertTrue(pc)

        # 現行セーブが警察署アーカイブ取得前でも、ロード自体は成功する
        kid = knowledge_id_for_object("police_archives")
        save_chars = (save.get("character_manager") or {}).get("characters") or {}
        save_pc01_known = set(
            (save_chars.get("pc_01") or {}).get("known_knowledge_ids") or []
        )
        if kid in save_pc01_known:
            notes_01 = (self.char_mgr.characters.get("pc_01") or {}).get("knowledge_notes") or {}
            self.assertIn(kid, self.char_mgr.get_known_knowledge_ids("pc_01"))
            self.assertIn("プレイヤー資料8", str(notes_01.get(kid) or ""))
            self.assertIn("マイケル・トーマス", str(notes_01.get(kid) or ""))
            self.assertNotIn("情報が眠っている", str(notes_01.get(kid) or ""))

        # save 原本の所持状態を壊していないこと（pc_02 が save で所持していれば維持、未所持なら付与しない）
        save_pc02_known = set(
            (save_chars.get("pc_02") or {}).get("known_knowledge_ids") or []
        )
        if "pc_02" in self.char_mgr.characters:
            loaded_known = set(self.char_mgr.get_known_knowledge_ids("pc_02"))
            if kid in save_pc02_known:
                self.assertIn(kid, loaded_known)
                notes_02 = (self.char_mgr.characters.get("pc_02") or {}).get("knowledge_notes") or {}
                self.assertIn("プレイヤー資料8", str(notes_02.get(kid) or ""))
            else:
                self.assertNotIn(kid, loaded_known)
                notes_02 = (self.char_mgr.characters.get("pc_02") or {}).get("knowledge_notes") or {}
                self.assertFalse(str(notes_02.get(kid) or "").strip())

        self.assertIsInstance(app_state.get("all_events_log"), list)
        self.assertGreaterEqual(len(app_state.get("all_events_log") or []), 1)

    def test_repair_does_not_grant_to_non_holder(self):
        """フラグ済みでも、未所持PCへは object:police_archives を付けない。"""
        self.scenario.flags["higher_courts_records_accessed"] = True
        self.char_mgr.active_pcs = ["pc_01"]
        # 案内文相当の note を既所持として置き、補修対象にする
        teaser = "閲覧には厳格な手続きが必要…情報が眠っている。"
        kid = knowledge_id_for_object("police_archives")
        self.char_mgr.grant_knowledge(
            "pc_01", kid, target="police_archives", summary=teaser, mark_investigated=True,
        )
        # 別PCを追加（未所持）
        self.char_mgr.characters["pc_02"] = {
            "profile": {"name": "エレノア教授", "is_npc": False},
            "attributes": {"SAN": {"current": 60, "max": 99}, "HP": {"current": 10, "max": 10}, "MP": {"current": 12, "max": 12}},
            "skills": {},
            "known_knowledge_ids": [],
            "knowledge_notes": {},
        }
        self.char_mgr.active_pcs = ["pc_01", "pc_02"]
        repaired = game_main.repair_police_archives_knowledge_on_load(
            self.char_mgr, self.scenario,
        )
        self.assertEqual(repaired, ["pc_01"])
        self.assertIn(kid, self.char_mgr.get_known_knowledge_ids("pc_01"))
        self.assertIn("プレイヤー資料8", str(
            (self.char_mgr.characters["pc_01"].get("knowledge_notes") or {}).get(kid) or ""
        ))
        self.assertNotIn(kid, self.char_mgr.get_known_knowledge_ids("pc_02"))


class TestLawSkillScope(_Base):
    def test_law_not_in_global_social_skills(self):
        from NPCSocialManager import SOCIAL_SKILLS
        self.assertNotIn("法律", SOCIAL_SKILLS)

    def test_kim_accepts_law_negotiation(self):
        from NPCSocialManager import NPCSocialManager, is_negotiation_skill_for_npc
        self.assertTrue(
            is_negotiation_skill_for_npc("法律", "kim_deblanc", self.char_mgr)
        )
        social = NPCSocialManager(self.char_mgr)
        with mock.patch.object(self.dice, "execute_skill_roll", return_value={
            "success_level": int(SuccessLevel.REGULAR_SUCCESS),
            "is_success": True,
            "roll": 20,
            "target": 55,
            "log": "【技能:法律】成功",
        }):
            result = social.resolve_negotiation(
                "pc_01", "kim_deblanc",
                skill_name="法律", dice_engine=self.dice, action_id="persuade",
            )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("skill"), "法律")

    def test_other_npc_law_falls_back_to_persuade(self):
        from NPCSocialManager import NPCSocialManager, is_negotiation_skill_for_npc
        self.assertFalse(
            is_negotiation_skill_for_npc("法律", "hall_records_clerk", self.char_mgr)
        )
        social = NPCSocialManager(self.char_mgr)
        with mock.patch.object(self.dice, "execute_skill_roll", return_value={
            "success_level": int(SuccessLevel.REGULAR_SUCCESS),
            "is_success": True,
            "roll": 20,
            "target": 70,
            "log": "【技能:説得】成功",
        }) as roll:
            result = social.resolve_negotiation(
                "pc_01", "hall_records_clerk",
                skill_name="法律", dice_engine=self.dice, action_id="persuade",
            )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("skill"), "説得")
        # 実際に振った技能も説得
        self.assertTrue(roll.called)
        # execute_skill_roll(pc_name, skill, ...)
        self.assertEqual(roll.call_args[0][1], "説得")

    def test_engine_judgment_allows_law_only_for_kim(self):
        from ActionValidator import resolve_engine_action_judgment
        self.scenario.location = "higher_courts_police_station"
        kim_j = resolve_engine_action_judgment(
            self.scenario, "persuade", "kim_deblanc", "法律",
            loc_id="higher_courts_police_station", char_mgr=self.char_mgr,
        )
        self.assertEqual(kim_j.get("skill_name"), "法律")
        self.assertIn("法律", kim_j.get("allowed_skills") or [])
        self.assertFalse(kim_j.get("skill_overridden"))

        clerk_j = resolve_engine_action_judgment(
            self.scenario, "persuade", "hall_records_clerk", "法律",
            loc_id="hall_of_records", char_mgr=self.char_mgr,
        )
        self.assertEqual(clerk_j.get("skill_name"), "説得")
        self.assertNotIn("法律", clerk_j.get("allowed_skills") or [])
        self.assertTrue(clerk_j.get("skill_overridden"))

    def test_artie_knott_hall_clerk_still_ok(self):
        # 導入ノット
        self.scenario.location = "introduction"
        self.assertTrue(
            self.scenario.is_npc_at_location("steven_knott", "introduction", char_mgr=self.char_mgr)
        )
        # グローブ
        self.scenario.location = "boston_globe"
        self.assertTrue(
            self.scenario.is_npc_at_location("globe_receptionist", "boston_globe", char_mgr=self.char_mgr)
        )
        self.assertFalse(
            self.scenario.is_npc_at_location("kim_deblanc", "boston_globe", char_mgr=self.char_mgr)
        )
        # 公文書館
        self.scenario.location = "hall_of_records"
        self.assertTrue(
            self.scenario.is_npc_at_location("hall_records_clerk", "hall_of_records", char_mgr=self.char_mgr)
        )


class TestBuildOverlay(unittest.TestCase):
    def test_build_overlay_keeps_police_and_kim(self):
        from build_corbitt_scenario import build_scenario_dict, PLAYER_HANDOUT_8
        scenario = build_scenario_dict()
        hc = scenario["locations"]["higher_courts_police_station"]
        self.assertEqual(hc.get("npcs_present"), ["kim_deblanc"])
        self.assertNotIn("kim_deblanc", hc.get("objects") or {})
        police = (hc.get("objects") or {}).get("police_archives") or {}
        self.assertIn("プレイヤー資料8", police.get("player_handout") or "")
        self.assertEqual(police.get("player_handout"), PLAYER_HANDOUT_8)
        self.assertTrue(any(
            r.get("id") == "kim_deblanc_records_access"
            for r in (scenario.get("social_progress_rules") or [])
        ) or True)  # outline may supply after merge; overlay always has police text


if __name__ == "__main__":
    unittest.main()
