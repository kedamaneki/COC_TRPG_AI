"""
タスク8: Decision Case Dynamic Few-Shot / RAG 注入の単体テスト。

実行:
  python test_dynamic_few_shot.py
"""
from __future__ import annotations

import os
import tempfile
import unittest

from DecisionCaseStore import (
    DecisionCaseStore,
    build_decision_case,
    infer_decision_type,
    is_high_quality_case,
    normalize_decision_case,
)
from DecisionCaseRAG import (
    BUILTIN_QUALITY_CASES,
    build_dynamic_few_shot_block,
    build_query_context,
    filter_quality_cases,
    format_few_shot_block,
    retrieve_similar_cases,
    scrub_case_for_prompt,
)
import main


class FakeCharMgr:
    def __init__(self):
        self.characters = {
            "pc_01": {
                "profile": {"name": "探索者A", "occupation": "記者", "is_npc": False},
                "known_knowledge_ids": ["k_public_note"],
                "investigated_targets": ["desk"],
                "memo": "",
            },
            "pc_02": {
                "profile": {"name": "探索者B", "is_npc": False},
                "known_knowledge_ids": [],
                "investigated_targets": [],
                "memo": "",
            },
        }
        self.active_pcs = ["pc_01", "pc_02"]

    @property
    def active_pc_list(self):
        return list(self.active_pcs)

    def get_pc(self, pc_id):
        return self.characters.get(pc_id)

    def get_pc_name(self, pc_id):
        return ((self.get_pc(pc_id) or {}).get("profile") or {}).get("name", pc_id)

    def get_known_knowledge_ids(self, char_id):
        return list((self.characters.get(char_id) or {}).get("known_knowledge_ids") or [])

    def get_pc_investigated_targets(self, char_id):
        return set((self.characters.get(char_id) or {}).get("investigated_targets") or [])

    def get_insanity_states(self, pl_id):
        return []

    def build_character_sheet_summary(self, pl_id):
        return f"【シート】{self.get_pc_name(pl_id)}"

    def get_knowledge_notes_for_prompt(self, pl_id, **kwargs):
        return ""


def _quality_case(**kwargs):
    base = {
        "actor_id": "pc_demo",
        "legal_options": ["search", "move", "wait"],
        "chosen_action": {"action": "search", "target": "desk"},
        "observation": {"known_knowledge_ids": [], "investigated_targets": ["desk"]},
        "annotations": {
            "rule_legal": True,
            "knowledge_leak": False,
            "intervention_level": "none",
            "notes": "合法対象のみ調べる。",
        },
        "decision_type": "investigation",
    }
    base.update(kwargs)
    return build_decision_case(**base) if "actor_id" in base else normalize_decision_case(base)


class TestQualityFilter(unittest.TestCase):
    def test_accepts_autonomous_legal_case(self):
        case = normalize_decision_case({
            "legal_options": ["accept", "spend_luck"],
            "chosen_action": {"action": "spend_luck"},
            "annotations": {
                "rule_legal": True,
                "knowledge_leak": False,
                "intervention_level": "none",
            },
        })
        self.assertTrue(is_high_quality_case(case))

    def test_rejects_leak_force_illegal(self):
        leak = normalize_decision_case({
            "annotations": {"rule_legal": True, "knowledge_leak": True, "intervention_level": "none"},
        })
        force = normalize_decision_case({
            "annotations": {
                "rule_legal": True,
                "knowledge_leak": False,
                "intervention_level": "積極的",
                "forced_progress": True,
            },
        })
        illegal = normalize_decision_case({
            "annotations": {"rule_legal": False, "knowledge_leak": False, "intervention_level": "none"},
        })
        self.assertFalse(is_high_quality_case(leak))
        self.assertFalse(is_high_quality_case(force))
        self.assertFalse(is_high_quality_case(illegal))

    def test_store_load_quality_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DecisionCaseStore(
                path=os.path.join(tmp, "c.jsonl"),
                index_path=os.path.join(tmp, "i.json"),
            )
            good = build_decision_case(
                actor_id="pc_01",
                legal_options=["talk", "persuade", "move"],
                chosen_action={"action": "talk", "target": "clerk"},
                annotations={
                    "rule_legal": True,
                    "knowledge_leak": False,
                    "intervention_level": "none",
                },
                decision_type="npc_negotiation",
            )
            bad = build_decision_case(
                actor_id="pc_01",
                legal_options=["search"],
                chosen_action={"action": "search"},
                annotations={
                    "rule_legal": True,
                    "knowledge_leak": True,
                    "intervention_level": "none",
                },
            )
            store.append_case(good)
            store.append_case(bad)
            quality = store.load_quality_cases()
            self.assertEqual(len(quality), 1)
            self.assertEqual(quality[0]["case_id"], good["case_id"])


class TestMatcher(unittest.TestCase):
    def test_infer_decision_types(self):
        self.assertEqual(
            infer_decision_type({
                "legal_options": ["accept", "spend_luck", "push"],
                "chosen_action": {"action": "spend_luck"},
            }),
            "failure_recovery",
        )
        self.assertEqual(
            infer_decision_type({
                "legal_options": ["talk", "persuade", "move"],
                "chosen_action": {"action": "talk"},
            }),
            "npc_negotiation",
        )
        self.assertEqual(
            infer_decision_type({
                "legal_options": ["move", "search", "wait"],
                "chosen_action": {"action": "move"},
                "annotations": {"stagnation_cause": "chat_only"},
            }),
            "retreat_breakout",
        )

    def test_retrieve_by_decision_type_not_scenario(self):
        corpus = [
            normalize_decision_case({
                "case_id": "dc_fail",
                "decision_type": "failure_recovery",
                "legal_options": ["accept", "spend_luck", "push"],
                "chosen_action": {"action": "spend_luck"},
                "observation": {"location": "scenario_a_room", "known_knowledge_ids": []},
                "annotations": {
                    "rule_legal": True,
                    "knowledge_leak": False,
                    "intervention_level": "none",
                },
            }),
            normalize_decision_case({
                "case_id": "dc_talk",
                "decision_type": "npc_negotiation",
                "legal_options": ["talk", "persuade", "move"],
                "chosen_action": {"action": "talk"},
                "observation": {"location": "scenario_b_lobby", "known_knowledge_ids": []},
                "annotations": {
                    "rule_legal": True,
                    "knowledge_leak": False,
                    "intervention_level": "none",
                },
            }),
            normalize_decision_case({
                "case_id": "dc_force_bad",
                "decision_type": "failure_recovery",
                "legal_options": ["accept", "push"],
                "chosen_action": {"action": "push"},
                "annotations": {
                    "rule_legal": True,
                    "knowledge_leak": False,
                    "intervention_level": "積極的",
                    "forced_progress": True,
                },
            }),
        ]
        query = build_query_context(
            decision_type="failure_recovery",
            legal_options=["accept", "spend_luck", "push"],
        )
        hits = retrieve_similar_cases(query, corpus=corpus, limit=2, min_score=3.0)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0]["case_id"], "dc_fail")
        # FORCE ケースは品質フィルタで除外
        ids = [c["case_id"] for c, _ in hits]
        self.assertNotIn("dc_force_bad", ids)

        q2 = build_query_context(
            decision_type="npc_negotiation",
            legal_options=["talk", "persuade"],
        )
        hits2 = retrieve_similar_cases(q2, corpus=corpus, limit=1)
        self.assertEqual(hits2[0][0]["case_id"], "dc_talk")


class TestKnowledgeSafeInjection(unittest.TestCase):
    def test_scrub_rejects_unknown_knowledge(self):
        case = normalize_decision_case({
            "decision_type": "investigation",
            "legal_options": ["search"],
            "chosen_action": {"action": "search", "target": "glowing_idol"},
            "observation": {"known_knowledge_ids": ["k_secret_idol"]},
            "annotations": {
                "rule_legal": True,
                "knowledge_leak": False,
                "intervention_level": "none",
            },
        })
        cleaned = scrub_case_for_prompt(
            case,
            known_knowledge_ids=["k_public_note"],
            investigated_targets=["desk"],
            audience="pl",
        )
        self.assertIsNone(cleaned)

    def test_scrub_generalizes_unknown_target(self):
        case = normalize_decision_case({
            "decision_type": "investigation",
            "legal_options": ["search", "move"],
            "chosen_action": {"action": "search", "target": "secret_basement_door"},
            "observation": {"known_knowledge_ids": []},
            "annotations": {
                "rule_legal": True,
                "knowledge_leak": False,
                "intervention_level": "none",
            },
        })
        cleaned = scrub_case_for_prompt(
            case,
            known_knowledge_ids=[],
            investigated_targets=["desk"],
            audience="pl",
        )
        self.assertIsNotNone(cleaned)
        self.assertEqual(cleaned["chosen_target"], "（提示された対象）")

    def test_block_is_compact_and_schema_safe(self):
        block = format_few_shot_block(
            [{
                "decision_type": "failure_recovery",
                "legal_options": ["accept", "spend_luck"],
                "chosen_action": "spend_luck",
                "chosen_target": "",
                "notes": "合法選択肢のみから選ぶ。",
            }],
            audience="pl",
            query={"decision_type": "failure_recovery"},
        )
        self.assertIn("参考例", block)
        self.assertIn("failure_recovery", block)
        self.assertIn("spend_luck", block)
        self.assertLessEqual(len(block), 900)
        # JSON スキーマを上書きする指示がないこと
        self.assertNotIn("```json", block)
        self.assertNotIn('"speak_as"', block)


class TestPromptInjection(unittest.TestCase):
    def test_pl_prompt_contains_matched_few_shot(self):
        corpus = filter_quality_cases(BUILTIN_QUALITY_CASES) + [
            normalize_decision_case({
                "case_id": "dc_custom_fail",
                "decision_type": "failure_recovery",
                "legal_options": ["accept", "spend_luck", "push"],
                "chosen_action": {"action": "push"},
                "observation": {"known_knowledge_ids": []},
                "annotations": {
                    "rule_legal": True,
                    "knowledge_leak": False,
                    "intervention_level": "none",
                    "notes": "失敗後は合法分岐のみ。",
                },
            }),
        ]
        state = {
            "enable_decision_few_shot": True,
            "pending_decision": {
                "type": "POST_ROLL_FAILURE",
                "legal_options": ["accept", "spend_luck", "push"],
            },
            "last_system_result": {"success_level": "failure", "log": "失敗"},
        }
        prompt = main.generate_pl_prompt(
            "探索者A",
            ["机を見た"],
            ["作戦を考える"],
            location_info={"name": "書斎", "objects": {"desk": {"name": "机"}}},
            available_exits=[{"id": "hall", "name": "廊下"}],
            char_mgr=FakeCharMgr(),
            pl_id="pc_01",
            game_state=state,
            decision_few_shot_corpus=corpus,
        )
        self.assertIn("参考例", prompt)
        self.assertIn("failure_recovery", prompt)
        # 既存の重要指示・構造は維持
        self.assertIn("多層的な意識", prompt)
        self.assertIn("行動選択ルール", prompt)

    def test_kp_prompt_contains_few_shot(self):
        prompt = main.generate_kp_prompt(
            {"name": "書斎", "default_description": "薄暗い部屋", "objects": {}},
            last_pl_action={"action": "search", "target": "desk", "skill": "目星", "message": "調べる"},
            last_system_result={
                "log": "成功",
                "kp_instruction": "机の中身を描写",
                "success_level": "success",
            },
            state={"enable_decision_few_shot": True},
            decision_few_shot_corpus=BUILTIN_QUALITY_CASES,
        )
        self.assertIn("参考例", prompt)
        self.assertIn("キーパー", prompt)
        self.assertIn("システムからの指示", prompt)

    def test_disabled_flag_skips_injection(self):
        block = build_dynamic_few_shot_block(
            audience="pl",
            query=build_query_context(decision_type="investigation"),
            corpus=BUILTIN_QUALITY_CASES,
            enabled=False,
        )
        self.assertEqual(block, "")

        prompt = main.generate_pl_prompt(
            "探索者A",
            [],
            [],
            location_info={"name": "書斎", "objects": {}},
            char_mgr=FakeCharMgr(),
            pl_id="pc_01",
            game_state={"enable_decision_few_shot": False},
            decision_few_shot_corpus=BUILTIN_QUALITY_CASES,
        )
        self.assertNotIn("参考例（高品質 Decision Case", prompt)

    def test_luck_prompt_injects_failure_recovery(self):
        class LuckCharMgr(FakeCharMgr):
            def get_luck(self, pl_id):
                return 40

            def get_insanity_states(self, pl_id):
                return []

        prompt = main.generate_pl_luck_prompt(
            "探索者A",
            {
                "margin": 5,
                "skill_name": "目星",
                "target": "desk",
                "legal_options": ["accept", "spend_luck"],
            },
            LuckCharMgr(),
            "pc_01",
            ["IC"],
            ["OOC"],
            game_state={"enable_decision_few_shot": True},
            decision_few_shot_corpus=BUILTIN_QUALITY_CASES,
        )
        self.assertIn("参考例", prompt)
        self.assertIn("failure_recovery", prompt)
        self.assertIn("use_luck", prompt)


if __name__ == "__main__":
    unittest.main()
