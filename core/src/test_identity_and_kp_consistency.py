# -*- coding: utf-8 -*-
"""
AI人物認識とKP描写整合性の回帰テスト。

LLM実通信なし（モック）。save_autosave.json / pcs.json / npcs.json には書き込まない。
実行: python test_identity_and_kp_consistency.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ActionValidator import (
    PL_IDENTITY_MISMATCH_CODE,
    collect_pc_identity_profiles,
    detect_kp_narration_violations,
    detect_pl_identity_violation,
    detects_extra_permission_demand_after_grant,
    extract_public_confirmed_narration_parts,
    extract_resolved_skill_from_result,
    is_access_already_granted,
    scrub_system_log_for_public_ic,
)
from CharacterManager import CharacterManager
from DiceEngine import DiceEngine
from GameStateManager import GameStateManager
from ScenarioManager import ScenarioManager
import main as game_main


ROOT = Path(__file__).resolve().parent
CORBITT = ROOT / "scenario_corbitt.json"
NPCS = ROOT / "npcs.json"
SAVE = ROOT / "save_autosave.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        if NPCS.exists():
            self.npc_path.write_text(NPCS.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            self.npc_path.write_text("{}", encoding="utf-8")
        self.pc_path.write_text(json.dumps({
            "pc_01": {
                "profile": {
                    "name": "マクガフィン刑事",
                    "occupation": "警官（刑事）",
                    "is_npc": False,
                },
                "attributes": {
                    "POW": 55, "INT": 65,
                    "SAN": {"current": 55, "max": 99, "session_start": 55},
                    "HP": {"current": 12, "max": 12},
                    "MP": {"current": 11, "max": 11},
                    "LUCK": 45,
                },
                "skills": {"説得": 70, "目星": 65, "信用": 55},
                "known_knowledge_ids": [],
                "investigated_targets": [],
                "states": [],
            },
            "pc_02": {
                "profile": {
                    "name": "エレノア教授",
                    "occupation": "民俗学教授",
                    "is_npc": False,
                },
                "attributes": {
                    "POW": 60, "INT": 80,
                    "SAN": {"current": 60, "max": 99, "session_start": 60},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 12, "max": 12},
                    "LUCK": 50,
                },
                "skills": {"説得": 60, "目星": 70, "図書館": 70},
                "known_knowledge_ids": [],
                "investigated_targets": [],
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.char_mgr.active_pcs = ["pc_01", "pc_02"]
        self.state_mgr = GameStateManager(self.char_mgr)
        self.scenario = ScenarioManager(
            copy.deepcopy(json.loads(CORBITT.read_text(encoding="utf-8")))
        ) if CORBITT.exists() else ScenarioManager({
            "scenario_meta": {"title": "t"},
            "initial_state": {"location": "boston_globe", "flags": {}},
            "locations": {"boston_globe": {"name": "グローブ", "objects": {}, "connected_to": []}},
            "event_triggers": [],
        })
        self.dice = DiceEngine()
        self.orig_save_hash = _sha(SAVE) if SAVE.exists() else None
        self.orig_pc_hash = _sha(ROOT / "pcs.json") if (ROOT / "pcs.json").exists() else None
        self.orig_npc_hash = _sha(NPCS) if NPCS.exists() else None

    def tearDown(self):
        if self.orig_save_hash and SAVE.exists():
            self.assertEqual(_sha(SAVE), self.orig_save_hash)
        if self.orig_pc_hash and (ROOT / "pcs.json").exists():
            self.assertEqual(_sha(ROOT / "pcs.json"), self.orig_pc_hash)
        if self.orig_npc_hash and NPCS.exists():
            self.assertEqual(_sha(NPCS), self.orig_npc_hash)
        self.tmp.cleanup()


class TestPlIdentitySwitch(_Base):
    def test_01_pc_switch_updates_name_occupation_actor(self):
        state = {"active_pcs": ["pc_01", "pc_02"], "active_pc_id": "pc_01"}
        game_main.sync_pl_identity(state, self.char_mgr, "pc_01")
        self.assertEqual(state["pl_id"], "pc_01")
        self.assertEqual(state["actor_id"], "pc_01")
        self.assertIn("マクガフィン", state["char_name"])
        prompt1 = game_main.generate_pl_prompt(
            state["char_name"], [], [], char_mgr=self.char_mgr, pl_id="pc_01",
            active_pcs=["pc_01", "pc_02"],
            location_info={"name": "x", "objects": {}},
        )
        self.assertIn("マクガフィン刑事", prompt1)
        self.assertIn("警官", prompt1)

        game_main.sync_pl_identity(state, self.char_mgr, "pc_02")
        self.assertEqual(state["pl_id"], "pc_02")
        self.assertEqual(state["actor_id"], "pc_02")
        self.assertIn("エレノア", state["char_name"])
        prompt2 = game_main.generate_pl_prompt(
            "古い刑事名", [], [], char_mgr=self.char_mgr, pl_id="pc_02",
            active_pcs=["pc_01", "pc_02"],
            location_info={"name": "x", "objects": {}},
        )
        # 呼び出し側の古い char_name より actor_id 正本が勝つ
        self.assertIn("エレノア教授", prompt2)
        self.assertIn("民俗学教授", prompt2)
        self.assertIn("pc_02", prompt2)
        self.assertNotIn("操作キャラクター: 古い刑事名", prompt2)

    def test_02_history_labels_discourage_mimic(self):
        logs = [
            {
                "channel": "IC", "location": "boston_globe", "secret_to": None,
                "text": "マクガフィン刑事(PC1): 私はマクガフィン刑事です。",
                "meta": {"pc_id": "pc_01", "actor_id": "pc_01"},
            },
            {
                "channel": "IC", "location": "boston_globe", "secret_to": None,
                "text": "システム: 判定成功",
                "meta": {"kp_narrated": False},
            },
        ]
        ic, _ = game_main.format_prompt_history_logs(
            "pc_02", "boston_globe", logs, char_mgr=self.char_mgr,
        )
        joined = "\n".join(ic)
        self.assertIn("他探索者の発言", joined)
        self.assertIn("模倣", joined)
        self.assertIn("システム確定", joined)
        prompt = game_main.generate_pl_prompt(
            "エレノア教授", ic, [], char_mgr=self.char_mgr, pl_id="pc_02",
            active_pcs=["pc_01", "pc_02"],
            location_info={"name": "グローブ", "objects": {}},
        )
        self.assertIn("自己紹介に流用しない", prompt)
        self.assertIn("エレノア教授", prompt)


class TestPlIdentityValidation(_Base):
    def _others(self, self_id):
        return [p for p in collect_pc_identity_profiles(self.char_mgr, ["pc_01", "pc_02"])
                if p["pc_id"] != self_id]

    def test_03_reject_professor_claims_detective_name(self):
        v = detect_pl_identity_violation(
            "アーティさん、取材しているマクガフィン刑事です。",
            self_pc_id="pc_02",
            self_name="エレノア教授",
            self_occupation="民俗学教授",
            other_profiles=self._others("pc_02"),
        )
        self.assertIsNotNone(v)
        self.assertEqual(v["error_code"], PL_IDENTITY_MISMATCH_CODE)

    def test_04_allow_calling_other_pc(self):
        v = detect_pl_identity_violation(
            "マクガフィン刑事、こちらを見てください。",
            self_pc_id="pc_02",
            self_name="エレノア教授",
            self_occupation="民俗学教授",
            other_profiles=self._others("pc_02"),
        )
        self.assertIsNone(v)

    def test_05_reject_self_as_other_and_false_cop_intro(self):
        v1 = detect_pl_identity_violation(
            "エレノア、君は少し休んでみて。",
            self_pc_id="pc_02",
            self_name="エレノア教授",
            self_occupation="民俗学教授",
            other_profiles=self._others("pc_02"),
        )
        self.assertIsNotNone(v1)
        v2 = detect_pl_identity_violation(
            "刑事のトムと申します。",
            self_pc_id="pc_02",
            self_name="エレノア教授",
            self_occupation="民俗学教授",
            other_profiles=self._others("pc_02"),
        )
        self.assertIsNotNone(v2)

    def test_05b_apply_rejects_bad_identity_without_ic_commit(self):
        logs = []
        out = game_main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pc_action": {
                    "action": "talk",
                    "target": "artie_wilmott",
                    "dialogue": "マクガフィン刑事です。記事を見せてください。",
                },
            },
            "エレノア教授",
            "boston_globe",
            logs,
            scenario_mgr=self.scenario,
            char_mgr=self.char_mgr,
            pc_id="pc_02",
        )
        self.assertTrue(out.get("needs_pl_retry"))
        self.assertEqual(out.get("validation_error_code"), PL_IDENTITY_MISMATCH_CODE)
        self.assertFalse(any(
            (e.get("text") or "").startswith("エレノア教授") and "マクガフィン刑事です" in (e.get("text") or "")
            for e in logs
        ))

    def test_05c_apply_allows_callout(self):
        self.scenario.location = "higher_courts_police_station"
        # キムが居る前提の talk は配置依存のため reconcile 前の identity だけ見る
        v = detect_pl_identity_violation(
            "マクガフィン刑事、こちらを見てください。",
            self_pc_id="pc_02",
            self_name="エレノア教授",
            self_occupation="民俗学教授",
            other_profiles=self._others("pc_02"),
        )
        self.assertIsNone(v)


class TestFewShotIsolation(_Base):
    def test_06_few_shot_disclaimer_and_no_knowledge_leak(self):
        from DecisionCaseRAG import format_few_shot_block, scrub_case_for_prompt
        block = format_few_shot_block([
            {
                "decision_type": "investigation",
                "legal_options": ["search"],
                "chosen_action": "search",
                "chosen_target": "desk",
                "notes": "合法のみ",
            }
        ], audience="pl")
        self.assertIn("現在操作中のPCのものではない", block)
        case = {
            "case_id": "x",
            "decision_type": "investigation",
            "legal_options": ["search"],
            "chosen_action": {"action": "search", "target": "desk"},
            "observation": {"known_knowledge_ids": ["object:secret_idol"]},
            "annotations": {"notes": "ok", "quality": "high"},
        }
        # 未知知識は scrub で落ちる
        self.assertIsNone(scrub_case_for_prompt(
            case, known_knowledge_ids=[], investigated_targets=[], audience="pl",
        ))


class TestLuckPushOwner(_Base):
    def test_07_luck_owner_stays_on_original_actor(self):
        state = {
            "active_pcs": ["pc_01", "pc_02"],
            "active_pc_id": "pc_02",
            "pl_id": "pc_02",
            "char_name": "エレノア教授",
            "actor_id": "pc_02",
            "decision_owner_id": "pc_01",
            "current_loc": "boston_globe",
            "all_events_log": [],
            "pending_luck_burn": {
                "margin": 3,
                "skill_name": "説得",
                "target": "artie_wilmott",
                "original_action": "persuade",
                "decision_owner_id": "pc_01",
                "actor_id": "pc_01",
                "legal_options": ["accept", "spend_luck"],
            },
            "partial_system_log": "失敗",
            "pending_decision": {"decision_owner_id": "pc_01"},
        }
        owner = game_main.resolve_pending_decision_owner(
            state, state["pending_luck_burn"], fallback_pl_id="pc_02",
        )
        self.assertEqual(owner, "pc_01")
        with mock.patch.object(game_main, "call_pl_api", return_value={
            "use_luck": False, "pl_ooc_chat": "温存する", "speak_as": "PL",
        }) as mocked:
            with mock.patch.object(game_main, "resolve_luck_burn_decision", return_value={
                "log": "失敗確定", "action_id": "persuade", "target": "artie_wilmott",
                "roll_type": "skill", "status": 0,
            }):
                with mock.patch.object(game_main, "_maybe_auto_resolve_san_check_after_action",
                                       side_effect=lambda *a, **k: a[-1] if a else k.get("result")):
                    with mock.patch.object(game_main, "apply_system_roll_state_updates"):
                        with mock.patch.object(game_main, "_append_result_log_with_knowledge"):
                            with mock.patch.object(game_main, "bind_push_family_transaction_ids",
                                                   side_effect=lambda r, *a, **k: r):
                                with mock.patch.object(game_main, "clear_pending_decision"):
                                    with mock.patch.object(game_main, "sync_timeline_pending_phase"):
                                        game_main.step_luck_decision(
                                            state, self.char_mgr, self.dice, self.scenario,
                                            self.state_mgr, "pc_02", "エレノア教授",
                                        )
        # call_pl_api は所有者 pc_01 で呼ばれる
        self.assertEqual(mocked.call_args.kwargs.get("active_pc_id"), "pc_01")
        # 画面上の active_pc は書き換えない
        self.assertEqual(state["active_pc_id"], "pc_02")


class TestKpGuards(_Base):
    def test_08_reject_extra_permission_after_grant(self):
        self.scenario.flags["artie_reference_room_access_granted"] = True
        text = (
            "特別な許可を出しましょう。ただし、ルース・ブレイクが管理している資料室に"
            "入室する際は、彼の許可が必要です。"
        )
        bad = detect_kp_narration_violations(
            text,
            scenario_mgr=self.scenario,
            last_system_result={
                "log": "アクセス許可が出た",
                "social": {"access_just_granted": True},
                "success_level": 2,
            },
            settled={"access_granted": True},
        )
        self.assertIn("extra_permission_after_grant", bad)

    def test_08b_generic_other_approver_and_location(self):
        # 別名の承認者・別フラグでも検出
        self.scenario.flags["library_archives_access_granted"] = True
        text = "閲覧は可能です。ただし受付の山田の承認が必要です。"
        self.assertTrue(detects_extra_permission_demand_after_grant(text))
        bad = detect_kp_narration_violations(
            text,
            scenario_mgr=self.scenario,
            last_system_result={"success_level": 2, "dice_success": True},
            settled={"access_granted": True},
        )
        self.assertIn("extra_permission_after_grant", bad)
        # 技能取り違えも汎用
        bad2 = detect_kp_narration_violations(
            "あなたの歴史が見事に当たった。",
            last_pl_action={"skill": "歴史"},
            last_system_result={
                "skill_name": "図書館", "dice_success": True, "success_level": 2,
                "log": "〈図書館〉で判定し成功。",
            },
            settled={"resolved_skill": "図書館", "proposed_skill": "歴史"},
        )
        self.assertTrue(any(x.startswith("wrong_skill_success") for x in bad2))

    def test_08c_past_permission_mention_not_rejected(self):
        text = (
            "通常は閲覧禁止で許可が必要だったが、今回はすでに許可済みだ。"
            "切り抜きを調べてよい。"
        )
        self.assertFalse(detects_extra_permission_demand_after_grant(text))
        bad = detect_kp_narration_violations(
            text,
            last_system_result={"dice_success": True, "success_level": 2},
            settled={"access_granted": True},
        )
        self.assertNotIn("extra_permission_after_grant", bad)

    def test_09_reject_wrong_skill_success_claim(self):
        text = "あなたの目星が見事に当たった。重要なファイルが広がる。"
        result = {
            "log": "【判定条件・システム確定】PL提案技能〈目星〉を採用せず、〈信用〉で判定します。\n成功。",
            "success_level": 2,
            "dice_success": True,
            "skill_name": "信用",
            "confirmed_fact": "資料8相当",
        }
        self.assertEqual(extract_resolved_skill_from_result(result, {"skill": "目星"}), "信用")
        bad = detect_kp_narration_violations(
            text,
            last_pl_action={"skill": "目星", "action": "search"},
            last_system_result=result,
            settled={"resolved_skill": "信用", "proposed_skill": "目星"},
        )
        self.assertTrue(any(x.startswith("wrong_skill_success") for x in bad))

    def test_10_reject_san_memory_wipe(self):
        bad = detect_kp_narration_violations(
            "衝撃で記憶を失った。持っていた知識が消えた。",
            last_system_result={"san_auto_resolved": True, "san_loss": 5, "success_level": 0},
            settled={},
        )
        self.assertIn("san_overclaim_memory_or_incapacity", bad)

    def test_11_allow_past_fail_current_success(self):
        text = "以前は失敗したが、今回は成功した。手がかりを見つけた。"
        bad = detect_kp_narration_violations(
            text,
            last_system_result={"dice_success": True, "success_level": 2, "confirmed_fact": "手紙"},
            settled={"resolved_skill": "目星"},
        )
        self.assertNotIn("success_negated", bad)
        self.assertNotIn("failure_flipped_to_success", bad)

    def test_12_reject_invented_pc_dialogue(self):
        bad = detect_kp_narration_violations(
            "あなたは『次は地下室へ向かおう』と言った。",
            last_pl_action={"dialogue": "机を調べる。", "action": "search"},
            last_system_result={"success_level": 2},
        )
        self.assertIn("invented_pc_dialogue", bad)

    def test_13_regen_fallback_does_not_reroll_or_grant(self):
        state = {
            "current_loc": "higher_courts_police_station",
            "all_events_log": [{
                "channel": "IC",
                "location": "higher_courts_police_station",
                "secret_to": None,
                "text": "システム: 〈信用〉成功。資料を得た。",
                "meta": {"action_id": "search", "kp_narrated": False, "target": "police_archives"},
            }],
            "last_pl_action": {"action": "search", "target": "police_archives", "skill": "目星"},
            "last_system_result": {
                "log": "【判定条件・システム確定】〈信用〉で判定。成功。【確定手がかり】資料8",
                "confirmed_fact": "資料8本文",
                "handout_text": "資料8本文",
                "dice_success": True,
                "success_level": 2,
                "skill_name": "信用",
                "target": "police_archives",
                "kp_instruction": "成功を描写。secret_hidden_basement を匂わせよ。",
            },
            "pending_san_check": None,
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
            "actor_id": "pc_01",
        }
        self.scenario.location = "higher_courts_police_station"
        bad_kp = {
            "should_speak": True,
            "speak_mode": "system_narration",
            "text": "あなたの目星が見事に当たった。",
        }

        def fake_api(prompt, max_retries=3, fallback_text="", allow_fallback=True):
            return game_main.parse_kp_response(bad_kp)

        with mock.patch.object(game_main, "call_kp_api", side_effect=fake_api):
            with mock.patch.object(game_main, "process_system_action") as proc:
                with mock.patch.object(game_main, "apply_knowledge_grants_from_result") as grant:
                    with mock.patch.object(game_main, "evaluate_and_apply_stagnation_intervention") as stag:
                        ok = game_main.step_kp_eval(
                            state, self.scenario, state["all_events_log"][0],
                            char_mgr=self.char_mgr, max_regen=1,
                        )
        self.assertTrue(ok)
        self.assertTrue(state["all_events_log"][0]["meta"]["kp_narrated"])
        proc.assert_not_called()
        grant.assert_not_called()
        stag.assert_not_called()
        kp_texts = [e["text"] for e in state["all_events_log"] if str(e.get("text") or "").startswith("KP:")]
        self.assertTrue(kp_texts)
        self.assertNotIn("目星が見事に当たった", kp_texts[-1])
        self.assertNotIn("kp_instruction", kp_texts[-1])
        self.assertNotIn("secret_hidden", kp_texts[-1])

    def test_13b_fallback_excludes_internal_fields(self):
        result = {
            "log": "成功。【確定手がかり】公開手がかりA\n【秘密開示】secret_foo: 表向きの説明文",
            "confirmed_fact": "公開手がかりA",
            "kp_instruction": "地下室の偶像を匂わせろ",
            "npc_roleplay": {"prompt_block": "内部演技指示XYZ"},
            "dice_success": True,
            "success_level": 2,
            "skill_name": "信用",
        }
        parts = extract_public_confirmed_narration_parts(result, fallback_text="")
        joined = "\n".join(parts)
        self.assertIn("公開手がかりA", joined)
        self.assertNotIn("kp_instruction", joined)
        self.assertNotIn("地下室の偶像を匂わせろ", joined)
        self.assertNotIn("内部演技指示XYZ", joined)
        self.assertNotIn("secret_foo", joined)
        # 開示本文は残ってよい
        self.assertIn("表向きの説明文", scrub_system_log_for_public_ic(result["log"]))

        fb = game_main.build_safe_kp_fallback_narration(
            scenario_mgr=self.scenario,
            last_pl_action={"skill": "目星"},
            last_system_result=result,
        )
        text = fb.get("text") or ""
        self.assertNotIn("kp_instruction", text)
        self.assertNotIn("地下室の偶像", text)
        self.assertNotIn("内部演技指示", text)
        self.assertNotIn("secret_foo", text)
        self.assertIn("公開手がかりA", text)

    def test_14_invalid_empty_does_not_set_kp_narrated(self):
        state = {
            "current_loc": "study",
            "all_events_log": [{
                "channel": "IC", "location": "study", "secret_to": None,
                "text": "システム: 成功",
                "meta": {"kp_narrated": False},
            }],
            "last_pl_action": {"action": "search", "target": "desk"},
            "last_system_result": {"log": "成功", "success_level": 2},
            "pending_san_check": None,
        }
        with mock.patch.object(game_main, "call_kp_api", return_value={
            "should_speak": True, "speak_mode": "system_narration", "text": "",
        }):
            ok = game_main.step_kp_eval(state, self.scenario, state["all_events_log"][0])
        self.assertFalse(ok)
        self.assertFalse(state["all_events_log"][0]["meta"]["kp_narrated"])

    def test_15_pl_identity_retry_capped(self):
        state = {
            "current_loc": "boston_globe",
            "all_events_log": [],
            "active_pcs": ["pc_01", "pc_02"],
            "active_pc_id": "pc_02",
            "pl_id": "pc_02",
            "char_name": "エレノア教授",
            "actor_id": "pc_02",
            "pending_san_check": None,
            "pending_push_roll": None,
            "last_system_result": None,
            "stagnation_pl_hint": None,
            "pl_discussion_mode": False,
        }
        bad = {
            "thought": "",
            "should_speak": True,
            "speak_as": "PC",
            "pl_ooc_chat": "",
            "pc_action": {
                "action": "talk",
                "target": "artie_wilmott",
                "skill": "",
                "message": "マクガフィン刑事です",
                "dialogue": "マクガフィン刑事です。記事をください。",
            },
        }
        calls = {"n": 0}

        def fake_pl(*a, **k):
            calls["n"] += 1
            return bad

        with mock.patch.object(game_main, "prepare_active_pc_for_pl_turn", return_value=True):
            with mock.patch.object(game_main, "call_pl_api", side_effect=fake_pl):
                with mock.patch.object(game_main, "ensure_force_ic_action_phase", return_value=False):
                    with mock.patch.object(game_main, "is_force_ic_action_phase", return_value=False):
                        out = game_main.step_pl_turn(
                            state, self.char_mgr, self.scenario, "pc_02", "エレノア教授",
                            state_mgr=self.state_mgr,
                        )
        # 初回 + validation retry 上限2 = 最大3。無限ループしない
        self.assertLessEqual(calls["n"], 3)
        self.assertEqual(calls["n"], 3)
        self.assertTrue(out.get("needs_pl_retry"))
        self.assertTrue(out.get("validation_regen_capped"))
        self.assertTrue(out.get("transaction_id"))
        # 次PCへの再選択（同一生成の連鎖を切る）
        self.assertNotEqual(state.get("active_pc_id"), "pc_02")
        self.assertTrue(any(
            (e.get("meta") or {}).get("hand_off")
            and (e.get("meta") or {}).get("validation_regen_capped")
            for e in state["all_events_log"]
        ))
        # 制御返却後、停滞計上は同一 transaction で一度だけ
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        before = int(self.state_mgr.stagnation_tracker.get("streak") or 0)
        out1 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        after = int(self.state_mgr.stagnation_tracker.get("streak") or 0)
        self.assertEqual(after, before + 1)
        self.assertTrue((out1 or {}).get("counted") or after == before + 1)
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertTrue((out2 or {}).get("skipped_duplicate"))
        self.assertEqual(
            int(self.state_mgr.stagnation_tracker.get("streak") or 0), after,
        )
        # 同一 tid では手番交代フラグが保持され、active_pc は据え置き
        tid = str(out.get("transaction_id") or "")
        self.assertEqual(state.get("validation_regen_cap_advanced_tid"), tid)
        self.assertNotEqual(state.get("active_pc_id"), "pc_02")
        pc_after_first = state.get("active_pc_id")
        self.assertEqual(state.get("active_pc_id"), pc_after_first)
        # 矛盾文は IC に採用されない
        self.assertFalse(any(
            "マクガフィン刑事です" in str(e.get("text") or "") and e.get("channel") == "IC"
            and not str(e.get("text") or "").startswith("[システム]")
            for e in state["all_events_log"]
            if not str(e.get("text") or "").startswith("[システム]")
        ))
        # 次ステップは kp_opening ではなく PL 応答経路。連鎖は1往復で止まる
        next_step = game_main.determine_timeline_next_step(
            state, state["char_name"], self.scenario,
            state_mgr=self.state_mgr, char_mgr=self.char_mgr,
        )
        self.assertIn(next_step, ("pl_speak", "free_chat"))
        with mock.patch.object(game_main, "step_pl_turn", return_value=out) as mocked_turn:
            pause, actors = game_main.run_timeline_chain(
                state, managers, max_chain=5,
            )
        self.assertEqual(mocked_turn.call_count, 1)

    def test_15b_is_access_generic_flag(self):
        self.scenario.flags["hall_of_records_access_granted"] = True
        self.assertTrue(is_access_already_granted(
            self.scenario, {}, current_loc="hall_of_records",
        ))
        # 無関係ロケの許可フラグだけでは、別ロケを「許可済み」とみなさない
        self.assertFalse(is_access_already_granted(
            self.scenario, {}, current_loc="boston_globe",
        ))


class TestAcceptanceCriteria(_Base):
    """受け入れ条件5点の回帰。"""

    def test_a1_professor_detective_not_confused(self):
        others = [p for p in collect_pc_identity_profiles(self.char_mgr, ["pc_01", "pc_02"])
                  if p["pc_id"] != "pc_02"]
        self.assertIsNotNone(detect_pl_identity_violation(
            "マクガフィン刑事です。記事を見せてください。",
            self_pc_id="pc_02", self_name="エレノア教授",
            self_occupation="民俗学教授", other_profiles=others,
        ))
        self.assertIsNone(detect_pl_identity_violation(
            "マクガフィン刑事、資料は見つかりましたか？",
            self_pc_id="pc_02", self_name="エレノア教授",
            self_occupation="民俗学教授", other_profiles=others,
        ))

    def test_a2_kp_does_not_overturn_grant_or_result(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_reference_room_access_granted"] = True
        bad = detect_kp_narration_violations(
            "ただし受付の追加承認が必要です。",
            scenario_mgr=self.scenario,
            last_system_result={
                "log": "アクセス許可が出た", "social": {"access_just_granted": True},
                "success_level": 2, "dice_success": True, "skill_name": "説得",
            },
            last_pl_action={"skill": "説得", "target": "artie_wilmott"},
            settled={"access_granted": True},
        )
        self.assertIn("extra_permission_after_grant", bad)
        bad_skill = detect_kp_narration_violations(
            "あなたの目星が見事に当たった。",
            last_pl_action={"skill": "信用"},
            last_system_result={
                "skill_name": "信用", "dice_success": True, "success_level": 2,
                "log": "〈信用〉成功",
            },
        )
        self.assertTrue(any(str(v).startswith("wrong_skill") for v in bad_skill))

    def test_a3_regen_cap_turn_and_stagnation_once(self):
        state = {
            "current_loc": "boston_globe",
            "all_events_log": [],
            "active_pcs": ["pc_01", "pc_02"],
            "active_pc_id": "pc_02",
            "pl_id": "pc_02",
            "char_name": "エレノア教授",
            "actor_id": "pc_02",
            "pending_san_check": None,
            "pending_push_roll": None,
            "last_system_result": None,
            "stagnation_pl_hint": None,
            "pl_discussion_mode": False,
        }
        bad = {
            "thought": "", "should_speak": True, "speak_as": "PC", "pl_ooc_chat": "",
            "pc_action": {
                "action": "talk", "target": "artie_wilmott", "skill": "",
                "message": "マクガフィン刑事です",
                "dialogue": "マクガフィン刑事です。",
            },
        }
        with mock.patch.object(game_main, "prepare_active_pc_for_pl_turn", return_value=True):
            with mock.patch.object(game_main, "call_pl_api", return_value=bad):
                with mock.patch.object(game_main, "ensure_force_ic_action_phase", return_value=False):
                    with mock.patch.object(game_main, "is_force_ic_action_phase", return_value=False):
                        out = game_main.step_pl_turn(
                            state, self.char_mgr, self.scenario, "pc_02", "エレノア教授",
                            state_mgr=self.state_mgr,
                        )
        self.assertTrue(out.get("validation_regen_capped"))
        first_pc = state.get("active_pc_id")
        self.assertNotEqual(first_pc, "pc_02")
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        d1 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        streak = int(self.state_mgr.stagnation_tracker.get("streak") or 0)
        d2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertTrue((d2 or {}).get("skipped_duplicate"))
        self.assertEqual(int(self.state_mgr.stagnation_tracker.get("streak") or 0), streak)
        # 同一 tid の再 advance はしない
        self.assertEqual(state.get("active_pc_id"), first_pc)
        self.assertEqual(
            state.get("validation_regen_cap_advanced_tid"),
            out.get("transaction_id"),
        )
        self.assertIsNotNone(d1)

    def test_a4_stagnation_hint_set_and_cleared_on_progress(self):
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        state = {
            "current_loc": "boston_globe",
            "all_events_log": [],
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
            "active_pc_id": "pc_01",
            "active_pcs": ["pc_01", "pc_02"],
            "intervention_level": "standard",
            "stagnation_pl_hint": None,
            "last_pl_action": {
                "action": "wait", "target": "", "skill": "", "dialogue": "",
                "needs_pl_retry": True,
                "validation_error_code": "identity_mismatch",
                "transaction_id": "hint-tid-1",
            },
            "last_system_result": None,
            "pending_san_check": None,
        }
        # ストリークを介入閾値近くまで積む
        for i in range(3):
            state["last_pl_action"] = {
                "action": "wait", "target": "", "skill": "", "dialogue": "",
                "needs_pl_retry": True,
                "validation_error_code": "identity_mismatch",
                "transaction_id": f"hint-tid-{i}",
            }
            game_main.evaluate_and_apply_stagnation_intervention(
                state, managers, after_step="pl_speak",
            )
        # STANDARD 介入でヒントが立つことを直接確認
        applied = game_main.apply_stagnation_intervention(
            state, managers, game_main.InterventionLevel.STANDARD,
            {"streak": 3, "cause": "invalid_loop"},
        )
        self.assertIn("pl_hint", applied["actions"])
        self.assertTrue(str(state.get("stagnation_pl_hint") or "").strip())
        # 実際の進展で解除
        game_main.reset_stagnation_state_on_progress(
            state, scenario_mgr=self.scenario, state_mgr=self.state_mgr, char_mgr=self.char_mgr,
        )
        self.assertFalse(str(state.get("stagnation_pl_hint") or "").strip())
        self.assertEqual(int(state.get("stagnation_streak") or 0), 0)

    def test_a5_soft_violation_does_not_force_safe_fallback(self):
        """代筆疑いのみでは安全フォールバックを連発しない。"""
        state = {
            "current_loc": "study",
            "all_events_log": [{
                "channel": "IC", "location": "study", "secret_to": None,
                "text": "システム: 〈目星〉成功。【確定手がかり】机の引き出しに手紙。",
                "meta": {"kp_narrated": False},
            }],
            "last_pl_action": {
                "action": "search", "target": "desk", "skill": "目星", "dialogue": "",
            },
            "last_system_result": {
                "log": "〈目星〉成功。【確定手がかり】机の引き出しに手紙。",
                "confirmed_fact": "机の引き出しに手紙。",
                "dice_success": True, "success_level": 2, "skill_name": "目星",
            },
            "pending_san_check": None,
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
            "actor_id": "pc_01",
        }
        soft_kp = {
            "should_speak": True,
            "speak_mode": "system_narration",
            # 硬矛盾なし・軟い代筆疑いのみ
            "text": "あなたは「この引き出しを開けよう」と言った。机に古い手紙がある。どうしますか？",
        }
        calls = {"n": 0}

        def fake_api(prompt, max_retries=3, fallback_text="", allow_fallback=True):
            calls["n"] += 1
            return game_main.parse_kp_response(soft_kp)

        with mock.patch.object(game_main, "call_kp_api", side_effect=fake_api):
            with mock.patch.object(game_main, "build_safe_kp_fallback_narration") as fb:
                ok = game_main.step_kp_eval(
                    state, self.scenario, state["all_events_log"][0],
                    char_mgr=self.char_mgr, max_regen=1,
                )
                fb.assert_not_called()
        self.assertTrue(ok)
        kp_texts = [e["text"] for e in state["all_events_log"] if str(e.get("text") or "").startswith("KP:")]
        self.assertTrue(kp_texts)
        # テンプレ安全フォールバック特有の定型ではなく、候補文が残る
        self.assertNotIn("許可は既に有効です", kp_texts[-1])


class TestOriginalFilesUntouched(_Base):
    def test_16_originals_unchanged_after_copy_load(self):
        if not SAVE.exists():
            self.skipTest("no save")
        before = _sha(SAVE)
        raw = json.loads(SAVE.read_text(encoding="utf-8"))
        save = copy.deepcopy(raw)
        game_main.restore_from_save_data(save, self.state_mgr, self.char_mgr, self.scenario)
        self.assertEqual(_sha(SAVE), before)


if __name__ == "__main__":
    unittest.main()
