from __future__ import annotations

import copy
import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path

import EvaluationCheckpoint as checkpoint
from EventIdentity import append_unified_event


class FakeManager:
    def __init__(self, data=None):
        self.data = copy.deepcopy(data or {})

    def export_to_dict(self):
        return copy.deepcopy(self.data)

    def load_from_dict(self, data):
        self.data = copy.deepcopy(data)


class FakeStateManager(FakeManager):
    def __init__(self, data=None):
        super().__init__(data)
        self._sync()

    def _sync(self):
        self.turn_count = self.data.get("turn_count", 0)
        self.current_scene_id = self.data.get("current_scene_id", "scene_001")
        self.pending_combat_defense = self.data.get("pending_combat_defense")

    def load_from_dict(self, data):
        super().load_from_dict(data)
        self._sync()


class FakeScenarioManager(FakeManager):
    def __init__(self, data=None):
        super().__init__(data)
        self.location = self.data.get("location", "study")
        self.bound = None

    def load_from_dict(self, data):
        super().load_from_dict(data)
        self.location = self.data.get("location", "study")

    def bind_game_state(self, state_mgr):
        self.bound = state_mgr


def fingerprints(**overrides):
    result = {
        "scenario_hash": "scenario",
        "source_hash": "source",
        "protected_source_hash": "protected-source",
        "evaluator_source_hash": "evaluator-source",
        "prompt_hash": "prompt",
        "pc_config_hash": "pcs",
        "kp_config_hash": "kp",
        "model_config": {"pl_model": "model-a"},
        "model_config_hash": "model",
        "evaluation_config_hash": "evaluation",
        "evaluation_config": {"max_cycles": 10},
    }
    result.update(overrides)
    return result


def base_state():
    state = {
        "session_id": "session-test",
        "current_loc": "archive",
        "active_pc_id": "pc_02",
        "pending_decision": None,
        "investigation_flow": {
            "attempt_rights": {
                "pc_01:clue:library:1": {"attempt_status": "USED"},
            },
            "exhausted_targets": ["clue"],
            "shared_information": {"clue": ["pc_01", "pc_02"]},
        },
        "director_v2": {
            "goal_manager": {
                "active_goal": "find_deed",
                "remaining_requirements": ["owner_name"],
                "completed_goals": ["enter_archive"],
            },
            "stall_detector": {
                "consecutive_no_progress": 3,
                "repeated_action": {"search:clue": 2},
                "stall_level": 2,
            },
        },
        "unified_event_log": [],
        "all_events_log": [{"channel": "IC", "text": "KP: test"}],
    }
    append_unified_event(state, {"event_type": "ROLL", "dice": 42, "scene_id": "scene_001"})
    return state


class EvaluationCheckpointUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.char = FakeManager({
            "characters": {
                "pc_01": {
                    "HP": 8, "SAN": 47, "Luck": 31,
                    "inventory": ["key"], "known_facts": ["fact-a"],
                },
            },
        })
        self.game = FakeStateManager({
            "turn_count": 7,
            "current_scene_id": "scene_001",
            "flags": {"found_deed": True},
            "stagnation_tracker": {"streak": 3, "last_progress_turn": 4},
            "combat_state": "INACTIVE",
            "pending_combat_defense": None,
        })
        self.scenario = FakeScenarioManager({
            "location": "archive",
            "current_phase": "investigation",
            "triggered_counts": {"deed_event": 1},
        })
        self.state = base_state()
        self.evaluator = {
            "total_cycles_observed": 5,
            "total_turns_observed": 7,
            "forced_action_count": 1,
            "guided_action_count": 2,
            "resume_count": 0,
            "event_log_offset": 1,
        }
        self.history = {
            "chat_history": [{"role": "assistant", "content": "history"}],
            "chat_session": [{"role": "assistant", "content": "history"}],
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self, cycle=5):
        return checkpoint.write_checkpoint(
            self.root, cycle=cycle, session_id="session-test", seed=2101,
            state=self.state, char_mgr=self.char, state_mgr=self.game,
            scenario_mgr=self.scenario, evaluator_state=self.evaluator,
            llm_history=self.history, fingerprints=fingerprints(),
            prior_segment_id="segment_001",
        )

    def test_save_load_restores_all_major_state_and_rng(self):
        random.seed(2101)
        path = self.write()
        expected_next_dice = [random.randint(1, 100) for _ in range(8)]

        self.char.data = {}
        self.game.data = {}
        self.scenario.data = {}
        self.state.clear()
        loaded = checkpoint.load_checkpoint(path)
        restored_state, evaluator, history = checkpoint.restore_checkpoint(
            loaded, char_mgr=self.char, state_mgr=self.game,
            scenario_mgr=self.scenario, current_fingerprints=fingerprints(), seed=2101,
        )

        self.assertEqual(expected_next_dice, [random.randint(1, 100) for _ in range(8)])
        self.assertEqual(restored_state["investigation_flow"]["attempt_rights"], {
            "pc_01:clue:library:1": {"attempt_status": "USED"},
        })
        self.assertEqual(restored_state["director_v2"]["goal_manager"]["active_goal"], "find_deed")
        self.assertEqual(restored_state["director_v2"]["stall_detector"]["consecutive_no_progress"], 3)
        self.assertEqual(self.char.data["characters"]["pc_01"]["Luck"], 31)
        self.assertEqual(self.game.data["stagnation_tracker"]["streak"], 3)
        self.assertEqual(evaluator, self.evaluator)
        self.assertEqual(history, self.history)
        self.assertIs(self.scenario.bound, self.game)
        self.assertTrue((path / "COMPLETE").is_file())

    def test_log_offset_and_event_ids_are_stable(self):
        first_path = self.write()
        first = checkpoint.load_checkpoint(first_path)
        event_id = first["payload"]["session_state"]["unified_event_log"][0]["event_id"]
        self.assertEqual(first["manifest"]["event_log_offset"], 1)
        self.assertEqual(first["manifest"]["event_id"], event_id)
        self.assertEqual(self.state["unified_event_log"][0]["event_id"], event_id)

    def test_incomplete_checkpoint_is_not_selected_as_latest(self):
        valid = self.write()
        broken = self.root / "checkpoints" / "cycle_000006"
        broken.mkdir(parents=True)
        (broken / "manifest.json").write_text("{}", encoding="utf-8")
        self.assertEqual(checkpoint.latest_checkpoint(self.root), valid)

    def test_checksum_corruption_is_rejected(self):
        path = self.write()
        (path / "state.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(checkpoint.CheckpointInvalid):
            checkpoint.load_checkpoint(path)

    def test_code_prompt_model_and_seed_mismatch_are_blocked(self):
        loaded = checkpoint.load_checkpoint(self.write())
        changed = fingerprints(
            source_hash="changed-source",
            prompt_hash="changed-prompt",
            model_config_hash="changed-model",
        )
        with self.assertRaises(checkpoint.ResumeBlocked) as raised:
            checkpoint.restore_checkpoint(
                loaded, char_mgr=self.char, state_mgr=self.game,
                scenario_mgr=self.scenario, current_fingerprints=changed, seed=999,
            )
        self.assertEqual(set(raised.exception.reasons), {
            "CHECKPOINT_SEED_MISMATCH",
            "CHECKPOINT_CODE_MISMATCH",
            "CHECKPOINT_PROMPT_MISMATCH",
            "CHECKPOINT_MODEL_MISMATCH",
        })

    def _compatibility(self, saved_max, requested_max, *, cycle=15, **current_overrides):
        saved = fingerprints(evaluation_config={"max_cycles": saved_max})
        saved.update({
            "seed": 2101,
            "cycle": cycle,
            "checkpoint_id": checkpoint.checkpoint_id_for_cycle(cycle),
        })
        current = fingerprints(evaluation_config={"max_cycles": requested_max}, **current_overrides)
        return checkpoint.assess_resume_compatibility(saved, current, 2101)

    def test_max_cycles_15_to_60_extension_is_allowed(self):
        result = self._compatibility(15, 60, cycle=15)
        self.assertEqual(result["validation_result"], "PASS")
        self.assertTrue(result["max_cycles_extended"])
        self.assertEqual(result["previous_limit"], 15)
        self.assertEqual(result["new_limit"], 60)

    def test_max_cycles_reduction_below_previous_and_checkpoint_is_blocked(self):
        result = self._compatibility(60, 20, cycle=40)
        self.assertEqual(result["validation_result"], "BLOCKED")
        self.assertIn("CHECKPOINT_MAX_CYCLES_REDUCTION", result["reasons"])
        self.assertIn("CHECKPOINT_MAX_CYCLES_BELOW_CHECKPOINT", result["reasons"])

    def test_unchanged_max_cycles_is_allowed(self):
        result = self._compatibility(15, 15, cycle=15)
        self.assertEqual(result["validation_result"], "PASS")
        self.assertFalse(result["max_cycles_extended"])

    def test_max_cycles_extension_does_not_allow_model_mismatch(self):
        result = self._compatibility(15, 60, model_config_hash="other-model")
        self.assertIn("CHECKPOINT_MODEL_MISMATCH", result["reasons"])

    def test_max_cycles_extension_does_not_allow_prompt_mismatch(self):
        result = self._compatibility(15, 60, prompt_hash="other-prompt")
        self.assertIn("CHECKPOINT_PROMPT_MISMATCH", result["reasons"])

    def test_max_cycles_extension_does_not_allow_scenario_mismatch(self):
        result = self._compatibility(15, 60, scenario_hash="other-scenario")
        self.assertIn("CHECKPOINT_SCENARIO_MISMATCH", result["reasons"])

    def test_cycle15_evaluator_only_migration_is_explicit_and_protected(self):
        saved = fingerprints(
            source_hash=checkpoint.COMPATIBLE_EVALUATOR_MIGRATIONS[
                checkpoint.MAX_CYCLES_EXTENSION_MIGRATION
            ]["from_source_hash"],
            evaluation_config={"max_cycles": 15},
        )
        saved.update({"seed": 2101, "cycle": 15, "checkpoint_id": "CHECKPOINT_CYCLE_000015"})
        current = fingerprints(
            source_hash="new-evaluator-source",
            protected_source_hash=checkpoint.COMPATIBLE_EVALUATOR_MIGRATIONS[
                checkpoint.MAX_CYCLES_EXTENSION_MIGRATION
            ]["protected_source_hash"],
            evaluation_config={"max_cycles": 60},
        )

        blocked = checkpoint.assess_resume_compatibility(saved, current, 2101)
        self.assertIn("CHECKPOINT_CODE_MISMATCH", blocked["reasons"])

        allowed = checkpoint.assess_resume_compatibility(
            saved,
            current,
            2101,
            compatible_migration=checkpoint.MAX_CYCLES_EXTENSION_MIGRATION,
        )
        self.assertEqual(allowed["validation_result"], "PASS")
        self.assertEqual(
            allowed["compatible_evaluator_migration"]["migration_id"],
            checkpoint.MAX_CYCLES_EXTENSION_MIGRATION,
        )

        tampered = dict(current, protected_source_hash="changed-gameplay-source")
        rejected = checkpoint.assess_resume_compatibility(
            saved,
            tampered,
            2101,
            compatible_migration=checkpoint.MAX_CYCLES_EXTENSION_MIGRATION,
        )
        self.assertIn("CHECKPOINT_CODE_MISMATCH", rejected["reasons"])

    def test_special_objective_contract_migration_is_exact_and_prompt_scoped(self):
        migration = checkpoint.COMPATIBLE_EVALUATOR_MIGRATIONS[
            checkpoint.SPECIAL_OBJECTIVE_COMBAT_CONTRACT_MIGRATION
        ]
        saved = fingerprints(
            source_hash=migration["from_source_hash"],
            prompt_hash=migration["from_prompt_hash"],
            evaluation_config={"max_cycles": 60},
        )
        saved.update({"seed": 2101, "cycle": 39, "checkpoint_id": "CHECKPOINT_CYCLE_000039"})
        current = fingerprints(
            source_hash="fixed-contract-source",
            protected_source_hash=migration["protected_source_hash"],
            prompt_hash=migration["to_prompt_hash"],
            evaluation_config={"max_cycles": 60},
        )

        allowed = checkpoint.assess_resume_compatibility(
            saved, current, 2101,
            compatible_migration=checkpoint.SPECIAL_OBJECTIVE_COMBAT_CONTRACT_MIGRATION,
        )
        self.assertEqual(allowed["validation_result"], "PASS")

        wrong_prompt = dict(current, prompt_hash="unexpected-prompt-change")
        rejected_prompt = checkpoint.assess_resume_compatibility(
            saved, wrong_prompt, 2101,
            compatible_migration=checkpoint.SPECIAL_OBJECTIVE_COMBAT_CONTRACT_MIGRATION,
        )
        self.assertIn("CHECKPOINT_PROMPT_MISMATCH", rejected_prompt["reasons"])

        wrong_source = dict(current, protected_source_hash="unexpected-gameplay-change")
        rejected_source = checkpoint.assess_resume_compatibility(
            saved, wrong_source, 2101,
            compatible_migration=checkpoint.SPECIAL_OBJECTIVE_COMBAT_CONTRACT_MIGRATION,
        )
        self.assertIn("CHECKPOINT_CODE_MISMATCH", rejected_source["reasons"])

    def test_runtime_data_snapshot_rolls_back_partial_cycle_mutation(self):
        runtime = self.root / "runtime_data"
        runtime.mkdir()
        (runtime / "pcs.json").write_text('{"hp": 10}', encoding="utf-8")
        path = checkpoint.write_checkpoint(
            self.root, cycle=5, session_id="session-test", seed=2101,
            state=self.state, char_mgr=self.char, state_mgr=self.game,
            scenario_mgr=self.scenario, evaluator_state=self.evaluator,
            llm_history=self.history, fingerprints=fingerprints(),
            prior_segment_id="segment_001", runtime_data_dir=runtime,
        )
        (runtime / "pcs.json").write_text('{"hp": 1}', encoding="utf-8")
        (runtime / "partial-cycle.tmp").write_text("unsafe", encoding="utf-8")
        loaded = checkpoint.load_checkpoint(path)
        checkpoint.restore_runtime_data(loaded, runtime)
        self.assertEqual((runtime / "pcs.json").read_text(encoding="utf-8"), '{"hp": 10}')
        self.assertFalse((runtime / "partial-cycle.tmp").exists())


class EvaluationCheckpointIntegrationTests(unittest.TestCase):
    def _run_cycles(self, state, start, end):
        for cycle in range(start, end + 1):
            die = random.randint(1, 100)
            state["dice_history"].append(die)
            state["flags"][f"cycle_{cycle}"] = die <= 50
            state["metrics"]["guided"] += int(die % 3 == 0)
            state["metrics"]["forced"] += int(die % 11 == 0)
            append_unified_event(state, {
                "event_type": "ROLL", "cycle": cycle, "dice": die,
                "scene_id": "scene_001", "action_origin": "AUTONOMOUS",
            })

    def test_continuous_10_equals_checkpoint_5_plus_resume_5(self):
        initial = {
            **base_state(), "dice_history": [], "flags": {},
            "metrics": {"guided": 0, "forced": 0},
        }
        random.seed(77)
        continuous = copy.deepcopy(initial)
        self._run_cycles(continuous, 1, 10)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            random.seed(77)
            split = copy.deepcopy(initial)
            self._run_cycles(split, 1, 5)
            char = FakeManager({"characters": {"pc_01": {"HP": 10}}})
            game = FakeStateManager({"turn_count": 5, "current_scene_id": "scene_001"})
            scenario = FakeScenarioManager({"location": "study"})
            path = checkpoint.write_checkpoint(
                root, cycle=5, session_id="integration", seed=77,
                state=split, char_mgr=char, state_mgr=game, scenario_mgr=scenario,
                evaluator_state={"total_cycles_observed": 5, "resume_count": 0},
                llm_history={"chat_history": [{"role": "user", "content": "context"}]},
                fingerprints=fingerprints(), prior_segment_id="segment_001",
            )

            restored, evaluator, history = checkpoint.restore_checkpoint(
                checkpoint.load_checkpoint(path), char_mgr=FakeManager(),
                state_mgr=FakeStateManager(), scenario_mgr=FakeScenarioManager(),
                current_fingerprints=fingerprints(), seed=77,
            )
            self._run_cycles(restored, 6, 10)

            # Event IDs are evaluator metadata, not game behavior.
            for event in restored["unified_event_log"]:
                event.pop("event_id", None)
                event.pop("raw_event_offset", None)
            for event in continuous["unified_event_log"]:
                event.pop("event_id", None)
                event.pop("raw_event_offset", None)
            self.assertEqual(continuous, restored)
            self.assertEqual(evaluator["total_cycles_observed"], 5)
            self.assertEqual(history["chat_history"][0]["content"], "context")

    def test_segment_merge_deduplicates_and_detects_gap_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = [
                {"event_id": "e1", "cycle": 1},
                {"event_id": "e2", "cycle": 2},
                {"event_id": "e3", "cycle": 3},
            ]
            checkpoint.write_segment(
                root, segment_id="segment_001", session_id="s",
                start_checkpoint_id=None, end_checkpoint_id="c2",
                resume_from_checkpoint_id=None, prior_segment_id=None,
                start_cycle=1, end_cycle=2, start_event_offset=0,
                events=events[:2], metrics_start={"cycles": 0},
                metrics_end={"cycles": 2}, status=checkpoint.STATUS_PAUSED,
            )
            checkpoint.write_segment(
                root, segment_id="segment_002", session_id="s",
                start_checkpoint_id="c2", end_checkpoint_id="c3",
                resume_from_checkpoint_id="c2", prior_segment_id="segment_001",
                start_cycle=3, end_cycle=3, start_event_offset=0,
                events=[events[1], events[2]], metrics_start={"cycles": 2},
                metrics_end={"cycles": 3}, status=checkpoint.STATUS_COMPLETED,
            )
            report = checkpoint.merge_segments(root)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["event_count"], 3)
            self.assertEqual(report["duplicate_events_removed"], 1)

            segment2_path = root / "segments" / "segment_002" / "segment.json"
            segment2 = json.loads(segment2_path.read_text(encoding="utf-8"))
            segment2["start_cycle"] = 5
            payload = json.dumps(segment2).encode("utf-8")
            segment2_path.write_bytes(payload)
            manifest_path = segment2_path.parent / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["checksum"] = hashlib.sha256(payload).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = checkpoint.merge_segments(root)
            self.assertIn("SEGMENT_GAP_DETECTED", {item["code"] for item in report["issues"]})

    def test_continuous_60_equals_20_plus_20_plus_20(self):
        initial = {
            **base_state(), "dice_history": [], "flags": {},
            "metrics": {"guided": 0, "forced": 0},
        }
        random.seed(2101)
        continuous = copy.deepcopy(initial)
        self._run_cycles(continuous, 1, 60)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            random.seed(2101)
            split = copy.deepcopy(initial)
            char = FakeManager({"characters": {"pc_01": {"HP": 10, "SAN": 50, "Luck": 40}}})
            game = FakeStateManager({"turn_count": 0, "current_scene_id": "scene_001"})
            scenario = FakeScenarioManager({"location": "study"})
            for segment_number, (start, end) in enumerate(((1, 20), (21, 40), (41, 60)), 1):
                self._run_cycles(split, start, end)
                game.data["turn_count"] = end
                game._sync()
                path = checkpoint.write_checkpoint(
                    root, cycle=end, session_id="split-60", seed=2101,
                    state=split, char_mgr=char, state_mgr=game, scenario_mgr=scenario,
                    evaluator_state={"total_cycles_observed": end, "resume_count": segment_number - 1},
                    llm_history={"chat_history": copy.deepcopy(split["all_events_log"])},
                    fingerprints=fingerprints(evaluation_config={"max_cycles": 60}),
                    prior_segment_id=f"segment_{segment_number:03d}",
                )
                if end < 60:
                    split, _, _ = checkpoint.restore_checkpoint(
                        checkpoint.load_checkpoint(path), char_mgr=char,
                        state_mgr=game, scenario_mgr=scenario,
                        current_fingerprints=fingerprints(evaluation_config={"max_cycles": 60}),
                        seed=2101,
                    )

            for event in split["unified_event_log"]:
                event.pop("event_id", None)
                event.pop("raw_event_offset", None)
            for event in continuous["unified_event_log"]:
                event.pop("event_id", None)
                event.pop("raw_event_offset", None)
            self.assertEqual(continuous, split)


if __name__ == "__main__":
    unittest.main()
