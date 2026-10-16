"""
タスク7: Decision Case 構造化抽出と LogEvaluator 6軸評価の単体テスト。

実行:
  python test_decision_case_evaluator.py
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from DecisionCaseStore import DecisionCaseStore, build_decision_case, normalize_decision_case
from LogEvaluator import (
    OUTCOME_DEFEAT_SAN,
    OUTCOME_DEFEAT_WIPE,
    OUTCOME_ERROR,
    OUTCOME_GAME_CLEAR,
    OUTCOME_RETREAT,
    classify_session_outcome,
    evaluate_session_metrics,
    evaluate_session_rp_logs,
    extract_and_persist_decision_cases,
    extract_decision_cases,
    record_decision_case,
)


class FakeCharMgr:
    def __init__(self):
        self.characters = {
            "pc_01": {
                "profile": {"name": "探索者A", "occupation": "記者", "age": 28, "gender": "女"},
                "memo": "慎重",
                "known_knowledge_ids": ["k_public_note"],
                "investigated_targets": ["desk"],
                "attributes": {
                    "SAN": {"current": 50, "max": 60, "session_start": 60, "session_start_san": 60},
                    "HP": {"current": 10, "max": 10},
                },
            },
            "pc_02": {
                "profile": {"name": "探索者B", "is_npc": False},
                "known_knowledge_ids": [],
                "investigated_targets": [],
                "attributes": {
                    "SAN": {"current": 40, "max": 55, "session_start": 55, "session_start_san": 55},
                    "HP": {"current": 11, "max": 11},
                },
            },
        }
        self.active_pcs = ["pc_01", "pc_02"]

    @property
    def active_pc_list(self):
        return list(self.active_pcs)

    def list_pc_ids(self):
        return ["pc_01", "pc_02"]

    def get_pc(self, pc_id):
        return self.characters.get(pc_id)

    def get_known_knowledge_ids(self, char_id):
        return list((self.characters.get(char_id) or {}).get("known_knowledge_ids") or [])

    def get_pc_investigated_targets(self, char_id):
        return set((self.characters.get(char_id) or {}).get("investigated_targets") or [])

    def get_stat_current(self, char_id, pool_key):
        attrs = (self.characters.get(char_id) or {}).get("attributes") or {}
        pool = attrs.get(pool_key) or {}
        if isinstance(pool, dict):
            return int(pool.get("current") or 0)
        return int(pool or 0)

    def is_pc_incapacitated(self, char_id, state_mgr=None):
        return self.get_stat_current(char_id, "HP") <= 0


def _sample_logs():
    return [
        {
            "channel": "IC",
            "location": "study",
            "secret_to": None,
            "text": "探索者A(PC): 机を調べる。",
            "meta": {
                "pc_id": "pc_01",
                "actor_id": "pc_01",
                "action_id": "search",
                "target": "desk",
                "skill": "目星",
                "needs_system": True,
                "transaction_id": "txn-search-001",
                "known_knowledge_ids": ["k_public_note"],
                "investigated_targets": [],
                "legal_options": ["search", "inspect", "move", "talk"],
                "turn": 3,
            },
        },
        {
            "channel": "IC",
            "location": "study",
            "secret_to": ["pc_01"],
            "text": "システム: 【技能:目星】成功。机の引き出しにメモを見つけた。",
            "meta": {
                "action_id": "search",
                "target": "desk",
                "transaction_id": "txn-search-001",
                "actor_id": "pc_01",
                "knowledge_ids": ["k_desk_memo"],
                "kp_narrated": True,
            },
        },
        {
            "channel": "IC",
            "location": "study",
            "secret_to": None,
            "text": "探索者A(PC): 棚を調べる。",
            "meta": {
                "pc_id": "pc_01",
                "actor_id": "pc_01",
                "action_id": "search",
                "target": "shelf",
                "skill": "目星",
                "needs_system": True,
                "transaction_id": "txn-search-002",
                "known_knowledge_ids": ["k_public_note", "k_desk_memo"],
                "legal_options": ["search", "inspect", "move"],
                "turn": 4,
            },
        },
        {
            "channel": "IC",
            "location": "study",
            "secret_to": None,
            "text": "システム: 【技能:目星】失敗。特に見つからない。",
            "meta": {
                "action_id": "search",
                "target": "shelf",
                "transaction_id": "txn-search-002",
                "actor_id": "pc_01",
            },
        },
    ]


class TestDecisionCaseStructure(unittest.TestCase):
    def test_normalize_and_build(self):
        case = build_decision_case(
            actor_id="pc_01",
            observation={"location": "study", "known_knowledge_ids": ["k1"]},
            legal_options=["search", "move"],
            chosen_action={"action": "search", "target": "desk", "transaction_id": "t1"},
            resolved_event_ids=["ev1"],
            annotations={"rule_legal": True, "knowledge_leak": False},
            session_id="sess_x",
            turn=2,
        )
        self.assertTrue(case["case_id"].startswith("dc_"))
        self.assertEqual(case["actor_id"], "pc_01")
        self.assertEqual(case["observation"]["location"], "study")
        self.assertEqual(case["legal_options"], ["search", "move"])
        self.assertEqual(case["chosen_action"]["action"], "search")
        self.assertFalse(case["annotations"]["knowledge_leak"])

        normalized = normalize_decision_case({"actor_id": "pc_02", "legal_options": "bad"})
        self.assertEqual(normalized["legal_options"], [])
        self.assertEqual(normalized["actor_id"], "pc_02")

    def test_extract_from_logs(self):
        char_mgr = FakeCharMgr()
        state = {"current_loc": "study", "pl_id": "pc_01", "rp_session_id": "sess_extract"}
        cases = extract_decision_cases(
            _sample_logs(),
            state=state,
            char_mgr=char_mgr,
            session_id="sess_extract",
            default_actor_id="pc_01",
        )
        self.assertEqual(len(cases), 2)
        first = cases[0]
        self.assertEqual(first["actor_id"], "pc_01")
        self.assertEqual(first["chosen_action"]["action"], "search")
        self.assertEqual(first["chosen_action"]["target"], "desk")
        self.assertIn("search", first["legal_options"])
        self.assertTrue(first["annotations"]["rule_legal"])
        self.assertFalse(first["annotations"]["knowledge_leak"])
        self.assertTrue(first["resolved_event_ids"])

    def test_store_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "decision_cases.jsonl")
            index = os.path.join(tmp, "decision_cases_index.json")
            store = DecisionCaseStore(path=path, index_path=index)
            saved = record_decision_case(
                actor_id="pc_01",
                observation={"location": "hall"},
                legal_options=["move", "wait"],
                chosen_action={"action": "move", "target": "study", "transaction_id": "txn-m1"},
                annotations={"rule_legal": True},
                session_id="sess_store",
                turn=1,
                store=store,
                persist=True,
            )
            self.assertTrue(os.path.exists(path))
            loaded = store.load_by_session("sess_store")
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["case_id"], saved["case_id"])
            self.assertTrue(store.has_case_id(saved["case_id"]))


class TestSixAxisMetrics(unittest.TestCase):
    def test_clean_session_scores_high(self):
        char_mgr = FakeCharMgr()
        state = {
            "all_events_log": _sample_logs(),
            "autonomous_pause_reason": "game_clear",
            "pl_id": "pc_01",
            "rp_session_id": "sess_clean",
            "rp_eval_last_summary": {"evaluated": 2, "saved_library": 2, "below_threshold": 0},
        }
        cases = extract_decision_cases(
            state["all_events_log"], state=state, char_mgr=char_mgr, session_id="sess_clean",
        )
        metrics = evaluate_session_metrics(
            state, char_mgr, decision_cases=cases, pause_reason="game_clear",
            rp_summary=state["rp_eval_last_summary"],
        )
        axes = metrics["axes"]
        self.assertEqual(metrics["outcome"]["outcome"], OUTCOME_GAME_CLEAR)
        self.assertFalse(metrics["outcome"]["is_system_failure"])
        self.assertGreaterEqual(axes["mechanical_accuracy"]["score"], 0.99)
        self.assertGreaterEqual(axes["knowledge_consistency"]["score"], 0.99)
        self.assertGreaterEqual(axes["operational_quality"]["score"], 0.99)
        self.assertIn("mechanical_accuracy", axes)
        self.assertIn("knowledge_consistency", axes)
        self.assertIn("autonomy", axes)
        self.assertIn("progress_efficiency", axes)
        self.assertIn("role_quality", axes)
        self.assertIn("operational_quality", axes)

    def test_validation_and_leak_lower_scores(self):
        logs = _sample_logs()
        # 違法＋二重処理＋知識漏洩のケースを追加
        logs.extend([
            {
                "channel": "IC",
                "location": "study",
                "text": "[システム] 不正な行動です",
                "meta": {"validation_error": True, "pc_id": "pc_01", "error_code": "illegal"},
            },
            {
                "channel": "IC",
                "location": "study",
                "text": "探索者A(PC): 地下室の偶像を調べる（未発見情報）",
                "meta": {
                    "pc_id": "pc_01",
                    "actor_id": "pc_01",
                    "action_id": "search",
                    "target": "glowing_idol",
                    "transaction_id": "txn-dup",
                    "known_knowledge_ids": ["k_public_note"],
                    "legal_options": ["search", "move"],
                    "action_used_unknown_knowledge": True,
                    "knowledge_ids": ["k_secret_idol"],
                    "turn": 5,
                },
            },
            {
                "channel": "IC",
                "location": "study",
                "text": "システム: 二重処理ガード",
                "meta": {
                    "action_id": "search",
                    "transaction_id": "txn-dup",
                    "actor_id": "pc_01",
                },
            },
            {
                "channel": "IC",
                "location": "study",
                "text": "探索者A(PC): 再度偶像を調べる",
                "meta": {
                    "pc_id": "pc_01",
                    "actor_id": "pc_01",
                    "action_id": "search",
                    "target": "glowing_idol",
                    "transaction_id": "txn-dup",
                    "duplicate_of": "txn-dup",
                    "known_knowledge_ids": ["k_public_note"],
                    "legal_options": ["search", "move"],
                    "action_origin": "SYSTEM_FORCED",
                    "forced_progress": True,
                    "intervention_level": 3,
                    "turn": 6,
                },
            },
        ])
        char_mgr = FakeCharMgr()
        state = {"all_events_log": logs, "pl_id": "pc_01", "rp_session_id": "sess_bad"}
        cases = extract_decision_cases(logs, state=state, char_mgr=char_mgr, session_id="sess_bad")
        metrics = evaluate_session_metrics(state, char_mgr, decision_cases=cases, pause_reason="stagnation")
        self.assertLess(metrics["axes"]["mechanical_accuracy"]["score"], 1.0)
        self.assertLess(metrics["axes"]["knowledge_consistency"]["score"], 1.0)
        self.assertLess(metrics["axes"]["autonomy"]["score"], 1.0)
        leak_cases = [c for c in cases if (c.get("annotations") or {}).get("knowledge_leak")]
        self.assertTrue(leak_cases)
        dup_cases = [c for c in cases if (c.get("annotations") or {}).get("duplicate_transaction")]
        self.assertTrue(dup_cases)


class TestOutcomeSeparation(unittest.TestCase):
    def test_game_clear(self):
        info = classify_session_outcome({"autonomous_pause_reason": "game_clear"})
        self.assertEqual(info["outcome"], OUTCOME_GAME_CLEAR)
        self.assertEqual(info["category"], "game")
        self.assertFalse(info["is_system_failure"])

    def test_system_error_vs_defeat_san(self):
        err = classify_session_outcome({"autonomous_pause_reason": "error"})
        self.assertEqual(err["outcome"], OUTCOME_ERROR)
        self.assertTrue(err["is_system_failure"])

        char_mgr = FakeCharMgr()
        for pc in char_mgr.characters.values():
            pc["attributes"]["SAN"]["current"] = 0
        defeat = classify_session_outcome(
            {"autonomous_pause_reason": "stagnation"},
            char_mgr,
        )
        self.assertEqual(defeat["outcome"], OUTCOME_DEFEAT_SAN)
        self.assertFalse(defeat["is_system_failure"])
        self.assertEqual(defeat["category"], "game")

        metrics = evaluate_session_metrics(
            {"autonomous_pause_reason": "stagnation", "all_events_log": []},
            char_mgr,
            decision_cases=[],
            pause_reason="stagnation",
        )
        # ゲーム内敗北は運用品質を落とさない（error と分離）
        self.assertGreaterEqual(metrics["axes"]["operational_quality"]["score"], 0.99)
        self.assertTrue(
            metrics["axes"]["operational_quality"]["detail"]["game_defeat_separated_from_error"]
        )

    def test_defeat_wipe_from_log_marker(self):
        logs = [{
            "channel": "IC",
            "text": "システム: 探索者全滅によりシナリオ終了。",
            "meta": {},
        }]
        info = classify_session_outcome(
            {"autonomous_pause_reason": "user_stop"},
            all_events_log=logs,
        )
        self.assertEqual(info["outcome"], OUTCOME_DEFEAT_WIPE)
        self.assertFalse(info["is_system_failure"])

    def test_retreat(self):
        logs = [{
            "channel": "OOC",
            "text": "KP: 探索者たちは撤退を決断した。",
            "meta": {"retreat": True, "game_outcome": "retreat"},
        }]
        info = classify_session_outcome(all_events_log=logs)
        self.assertEqual(info["outcome"], OUTCOME_RETREAT)
        self.assertEqual(info["category"], "game")

    def test_error_operational_score_zero(self):
        metrics = evaluate_session_metrics(
            {"autonomous_pause_reason": "error", "all_events_log": []},
            FakeCharMgr(),
            decision_cases=[],
            pause_reason="error",
        )
        self.assertEqual(metrics["axes"]["operational_quality"]["score"], 0.0)
        self.assertTrue(metrics["outcome"]["is_system_failure"])


class TestSessionIntegration(unittest.TestCase):
    def test_evaluate_session_persists_cases_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases_path = os.path.join(tmp, "decision_cases.jsonl")
            index_path = os.path.join(tmp, "decision_cases_index.json")
            metrics_path = os.path.join(tmp, "session_metrics.jsonl")
            store = DecisionCaseStore(path=cases_path, index_path=index_path)
            char_mgr = FakeCharMgr()
            state = {
                "all_events_log": _sample_logs(),
                "pl_id": "pc_01",
                "char_name": "探索者A",
                "autonomous_pause_reason": "game_clear",
                "current_loc": "study",
                "rp_session_id": "sess_int_001",
            }
            summary = evaluate_session_rp_logs(
                state,
                char_mgr,
                pl_id="pc_01",
                char_name="探索者A",
                skip_rp_judge=True,
                decision_store=store,
                metrics_path=metrics_path,
            )
            self.assertIsNotNone(summary)
            self.assertGreaterEqual(summary.get("decision_cases_saved", 0), 1)
            self.assertEqual(summary.get("session_outcome"), OUTCOME_GAME_CLEAR)
            self.assertTrue(os.path.exists(cases_path))
            self.assertTrue(os.path.exists(metrics_path))

            loaded = store.load_by_session("sess_int_001")
            self.assertGreaterEqual(len(loaded), 1)
            self.assertIn("observation", loaded[0])
            self.assertIn("legal_options", loaded[0])
            self.assertIn("chosen_action", loaded[0])
            self.assertIn("annotations", loaded[0])

            with open(metrics_path, encoding="utf-8") as fh:
                row = json.loads(fh.readline())
            self.assertIn("axes", row)
            self.assertEqual(len(row["axes"]), 6)
            self.assertIn("session_metrics_last", state)

            # 冪等: 再実行しても二重保存しない
            summary2 = evaluate_session_rp_logs(
                state,
                char_mgr,
                skip_rp_judge=True,
                decision_store=store,
                metrics_path=metrics_path,
            )
            self.assertEqual(summary2.get("decision_cases_saved", 0), 0)

    def test_extract_and_persist_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DecisionCaseStore(
                path=os.path.join(tmp, "c.jsonl"),
                index_path=os.path.join(tmp, "i.json"),
            )
            state = {
                "all_events_log": _sample_logs(),
                "pl_id": "pc_01",
                "rp_session_id": "sess_helper",
            }
            result = extract_and_persist_decision_cases(state, FakeCharMgr(), store=store)
            self.assertEqual(result["extracted"], 2)
            self.assertEqual(result["saved"], 2)
            self.assertEqual(len(state.get("decision_case_ids") or []), 2)


if __name__ == "__main__":
    unittest.main()
